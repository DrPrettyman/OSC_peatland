#!/usr/bin/env python3
"""Build the moorland-peat analysis mask on the Sentinel-1 grid.

A 10 m pixel is kept if it lies on peat in the England Peat Map (deep or shallow
peaty soils) and is not:
  - improved grassland (IMP), afforested (AFF), woodland (WOD) or REM-flagged
    (linear features: roads, tracks) in the England Peat Map status layer;
  - tree cover, built-up or open water in ESA WorldCover 2021;
  - radar-dark water: temporal-mean VV below -18 dB in every orbit (reservoir and
    flooded-pit margins).
Trees and water are buffered by 2 pixels (20 m) to drop edge effects (layover,
shadow, mixed pixels).

Writes code/data/ancillary/peat_mask.tif (uint8: 1 = keep). The mask is
plotted for checking in eda.ipynb.

    python code/make_mask.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import rasterio
from affine import Affine
from rasterio.features import rasterize
from rasterio.warp import transform_geom
from scipy.ndimage import binary_dilation

from s1stack import load_grid, load_stack

ROOT = Path(__file__).resolve().parent
ANC = ROOT / "data" / "ancillary"
EXCLUDE_FLAGS = ("IMP", "AFF", "WOD", "REM")
WATER_DB = -18.0


def rasterize_features(fc: dict, pred, grid: dict) -> np.ndarray:
    shapes = [(transform_geom("EPSG:4326", grid["crs"], f["geometry"]), 1)
              for f in fc["features"] if f["geometry"] and pred(f["properties"])]
    if not shapes:
        return np.zeros((grid["height"], grid["width"]), bool)
    return rasterize(shapes, out_shape=(grid["height"], grid["width"]),
                     transform=Affine(*grid["transform"]), fill=0, dtype="uint8").astype(bool)


def flagged(p: dict, k: str) -> bool:
    return bool((p.get(k) or "").strip())


def build_layers() -> dict[str, np.ndarray]:
    grid = load_grid()
    peat = json.loads((ANC / "peat_status.geojson").read_text())
    with rasterio.open(ANC / "worldcover.tif") as src:
        wc = src.read(1)
    dark = np.ones((grid["height"], grid["width"]), bool)
    for o in (1, 52, 103):
        _, s = load_stack(o)
        dark &= np.nanmean(s, 0) < WATER_DB

    layers = {"peat": rasterize_features(peat, lambda p: True, grid)}
    for k in EXCLUDE_FLAGS:
        layers[k] = rasterize_features(peat, lambda p, k=k: flagged(p, k), grid)
    buf = np.ones((5, 5), bool)  # 2-pixel buffer
    layers["trees"] = binary_dilation(wc == 10, buf)
    layers["water"] = binary_dilation((wc == 80) | dark, buf)
    layers["built"] = wc == 50
    keep = layers["peat"].copy()
    for k in (*EXCLUDE_FLAGS, "trees", "water", "built"):
        keep &= ~layers[k]
    layers["keep"] = keep
    return layers


def main() -> None:
    grid = load_grid()
    layers = build_layers()
    keep = layers["keep"]
    for k, v in layers.items():
        print(f"{k:6s} {v.mean():6.1%} of box")

    profile = dict(driver="GTiff", dtype="uint8", count=1, width=grid["width"], height=grid["height"],
                   crs=grid["crs"], transform=Affine(*grid["transform"]), compress="deflate", nodata=None)
    with rasterio.open(ANC / "peat_mask.tif", "w", **profile) as dst:
        dst.write(keep.astype("uint8"), 1)
    print(f"wrote {ANC / 'peat_mask.tif'}")


if __name__ == "__main__":
    main()
