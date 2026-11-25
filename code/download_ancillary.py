#!/usr/bin/env python3
"""Download land-cover and elevation layers on the Sentinel-1 grid, for masking.

Layers (all resampled nearest-neighbour onto code/data/s1_VV/grid.json):
  worldcover.tif     ESA WorldCover v200 (2021, 10 m) class codes
  dynamicworld.tif   Dynamic World V1 modal class over 2023-2024 (0-8)
  dw_trees.tif       Dynamic World mean 'trees' probability 2023-2024 (0-1)
  dem.tif            Copernicus GLO-30 DEM elevation (m)

    python code/download_ancillary.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import ee
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "ancillary"
GRID = ROOT / "data" / "s1_VV" / "grid.json"
load_dotenv(ROOT.parent / ".env")


def fetch(image: ee.Image, name: str, grid: dict, aoi: ee.Geometry) -> None:
    out = OUT / name
    if out.exists():
        print(f"skip {name}")
        return
    url = image.clip(aoi.buffer(2000)).getDownloadURL({
        "crs": grid["crs"], "crs_transform": grid["transform"],
        "dimensions": f"{grid['width']}x{grid['height']}", "format": "GEO_TIFF",
    })
    r = requests.get(url, timeout=600)
    r.raise_for_status()
    if not r.content.startswith((b"II*\x00", b"MM\x00*")):
        raise RuntimeError(f"{name}: not a GeoTIFF: {r.content[:200]!r}")
    out.write_bytes(r.content)
    print(f"wrote {out}")


def main() -> None:
    ee.Initialize(project=os.environ["EE_PROJECT"])
    OUT.mkdir(parents=True, exist_ok=True)
    grid = json.loads(GRID.read_text())
    aoi = ee.Geometry(json.loads((GRID.parent / "aoi.geojson").read_text()))

    wc = ee.ImageCollection("ESA/WorldCover/v200").first().select("Map").toUint8()
    fetch(wc, "worldcover.tif", grid, aoi)

    dw = (ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
          .filterBounds(aoi).filterDate("2023-01-01", "2025-01-01"))
    fetch(dw.select("label").mode().toUint8(), "dynamicworld.tif", grid, aoi)
    fetch(dw.select("trees").mean().toFloat(), "dw_trees.tif", grid, aoi)

    dem = ee.ImageCollection("COPERNICUS/DEM/GLO30_2024_1").filterBounds(aoi).select("DEM").mosaic()
    fetch(dem.toFloat().setDefaultProjection("EPSG:4326", None, 30), "dem.tif", grid, aoi)


if __name__ == "__main__":
    main()
