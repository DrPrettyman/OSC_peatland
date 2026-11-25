#!/usr/bin/env python3
"""Download England Peat Map layers (Natural England open data) for the study box.

  peat_status.geojson          England Peat Status, GHG and C storage (peat extent,
                               depth class `PSL`, land-use/vegetation class `new_pho`)
  restoration_register.geojson England Peat Map Peatland Restoration Register
  restoration_sites.csv        one row per register record: name, scheme, dates, area,
                               land use and restoration stage, grid reference

Both come from Natural England's ArcGIS Online feature services (Open Government
Licence; peat status © BGS & NSRI). Geometries are WGS84 GeoJSON.

    python code/download_peat_map.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "ancillary"
AOI = ROOT / "data" / "s1_VV" / "aoi.geojson"
BASE = "https://services.arcgis.com/JJzESW51TqeY9uat/arcgis/rest/services"
LAYERS = {
    "peat_status.geojson": "England_Peat_Status_GHG_and_C_Storage",
    "restoration_register.geojson": "England_Peat_Map_Peatland_Restoration_Register",
}


def bbox() -> str:
    ring = json.loads(AOI.read_text())["coordinates"][0]
    xs, ys = zip(*ring)
    return f"{min(xs)},{min(ys)},{max(xs)},{max(ys)}"


def query_all(service: str, page: int = 1000) -> dict:
    url = f"{BASE}/{service}/FeatureServer/0/query"
    feats, offset = [], 0
    while True:
        r = requests.get(url, timeout=120, params={
            "where": "1=1", "geometry": bbox(), "geometryType": "esriGeometryEnvelope",
            "inSR": 4326, "spatialRel": "esriSpatialRelIntersects", "outFields": "*",
            "outSR": 4326, "f": "geojson", "resultOffset": offset, "resultRecordCount": page,
        })
        r.raise_for_status()
        batch = r.json().get("features", [])
        feats += batch
        if len(batch) < page:
            break
        offset += page
    return {"type": "FeatureCollection", "features": feats}


def write_sites_csv(fc: dict, path: Path = OUT / "restoration_sites.csv") -> pd.DataFrame:
    """Tabulate the restoration register records (attributes only, no geometry)."""
    rows = [{
        "name": p["RestoID"],
        "geometry": p["Source_geometry"].lower(),  # "polygon" or "point" (point = grid reference only)
        "scheme": p["Src_Data"],
        "scheme_ref": p["Src_Ref"],
        "lead_org": p["Lead_Org"],
        "start": p["Act_Date"],
        "start_type": p["Date_Type"],
        "end": p["EndDate"],
        "area_ha": round(p["Hab_Amt"], 2),
        "land_use_before": p["GHG_LU"],
        "stage_before": p["Resto_stg"],
        "stage_target": p["Resto_end"],
        "easting": p["Easting"],
        "northing": p["Northing"],
        "actions": p["Act_Desc"],
    } for p in (f["properties"] for f in fc["features"])]
    df = pd.DataFrame(rows).sort_values(["geometry", "start", "name"], ascending=[False, True, True])
    df.to_csv(path, index=False)
    print(f"wrote {path}: {len(df)} records")
    return df


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, service in LAYERS.items():
        fc = query_all(service)
        (OUT / name).write_text(json.dumps(fc))
        print(f"wrote {OUT / name}: {len(fc['features'])} features")
        if name == "restoration_register.geojson":
            write_sites_csv(fc)


if __name__ == "__main__":
    main()
