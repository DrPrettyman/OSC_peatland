#!/usr/bin/env python3
"""Download Sentinel-1 GRD backscatter scenes over Bodmin Moor from Google Earth Engine.

Every scene in the date range that covers the study area is exported as a
single-band GeoTIFF (sigma0 in dB) on one fixed grid, so the files stack
pixel-for-pixel for time-series and per-pixel trend analysis. An index.csv
records each scene's acquisition time, platform, orbit pass and relative orbit,
so the analysis can restrict itself to a single viewing geometry.

Data: COPERNICUS/S1_GRD (IW mode). Earth Engine has already applied thermal
noise removal, radiometric calibration, terrain correction (SRTM 30 m) and
conversion to dB. The edge mask below removes low-value border noise (< -30 dB).

Usage
-----
    # once per machine (localhost mode avoids gcloud; see README)
    earthengine authenticate --auth_mode=localhost

    # list the matching scenes and per-orbit counts without downloading
    python code/download_s1.py --project my-gee-project --dry-run

    # download everything (all orbits) to code/data/s1_VV
    python code/download_s1.py --project my-gee-project

    # one relative orbit only, custom study boundary
    python code/download_s1.py --project my-gee-project \
        --aoi study_area.geojson --orbit-pass DESCENDING --rel-orbit 132

Re-running skips files that already exist, so an interrupted download resumes.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import ee
import requests
from dotenv import load_dotenv

COLLECTION = "COPERNICUS/S1_GRD"

# Placeholder study area: northern Bodmin Moor uplands (Rough Tor, Brown Willy,
# Crowdy). Replace with --aoi <geojson> once the peat boundary is chosen.
DEFAULT_BBOX = (-4.66, 50.55, -4.55, 50.63)  # lon_min, lat_min, lon_max, lat_max

NODATA = -9999.0
OUT_ROOT = Path(__file__).resolve().parent / "data"

# Settings such as EE_PROJECT can live in a .env file at the repository root.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def mask_edge(image: ee.Image) -> ee.Image:
    """Mask low-value border noise at scene edges."""
    edge = image.lt(-30.0)
    return image.updateMask(image.mask().And(edge.Not()))


def load_aoi(path: str | None, bbox: list[float] | None) -> ee.Geometry:
    if path:
        with open(path) as f:
            gj = json.load(f)
        if gj.get("type") == "FeatureCollection":
            feats = [ee.Feature(ee.Geometry(ft["geometry"])) for ft in gj["features"]]
            return ee.FeatureCollection(feats).geometry()
        if gj.get("type") == "Feature":
            return ee.Geometry(gj["geometry"])
        return ee.Geometry(gj)
    return ee.Geometry.Rectangle(list(bbox or DEFAULT_BBOX))


def build_collection(aoi, start, end, pol, orbit_pass, rel_orbits, allow_partial):
    col = (
        ee.ImageCollection(COLLECTION)
        .filterBounds(aoi)
        .filterDate(start, end)
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", pol))
        .filter(ee.Filter.eq("instrumentMode", "IW"))
    )
    if orbit_pass:
        col = col.filter(ee.Filter.eq("orbitProperties_pass", orbit_pass))
    if rel_orbits:
        col = col.filter(ee.Filter.inList("relativeOrbitNumber_start", rel_orbits))
    if not allow_partial:
        # Keep only scenes whose footprint fully contains the study area.
        col = col.filter(ee.Filter.contains(leftField=".geo", rightValue=aoi))
    return col.sort("system:time_start")


def fetch_metadata(col: ee.ImageCollection) -> list[dict]:
    props = [
        "system:index",
        "system:time_start",
        "platform_number",
        "orbitProperties_pass",
        "relativeOrbitNumber_start",
        "resolution_meters",
    ]
    cols = ee.Dictionary({p: col.aggregate_array(p) for p in props}).getInfo()
    n = len(cols["system:index"])
    if any(len(cols[p]) != n for p in props):
        sys.exit("Scene metadata is incomplete; cannot build index.")
    rows = []
    for i in range(n):
        t = datetime.fromtimestamp(cols["system:time_start"][i] / 1000, tz=timezone.utc)
        rows.append(
            {
                "scene_id": cols["system:index"][i],
                "datetime_utc": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "platform": f"S1{cols['platform_number'][i]}",
                "orbit_pass": cols["orbitProperties_pass"][i],
                "rel_orbit": int(cols["relativeOrbitNumber_start"][i]),
                "resolution_m": cols["resolution_meters"][i],
            }
        )
    return rows


def fixed_grid(aoi: ee.Geometry, crs: str, scale: float):
    """Snap the AOI bounds to a `scale` grid in `crs`; return transform and size."""
    ring = aoi.bounds(maxError=1, proj=crs).coordinates().getInfo()[0]
    xs, ys = [p[0] for p in ring], [p[1] for p in ring]
    x0 = math.floor(min(xs) / scale) * scale
    x1 = math.ceil(max(xs) / scale) * scale
    y0 = math.floor(min(ys) / scale) * scale
    y1 = math.ceil(max(ys) / scale) * scale
    transform = [scale, 0, x0, 0, -scale, y1]
    return transform, int(round((x1 - x0) / scale)), int(round((y1 - y0) / scale))


def scene_filename(row: dict, pol: str) -> str:
    t = row["datetime_utc"].replace("-", "").replace(":", "").rstrip("Z")
    return f"{t}_{row['platform']}_{row['orbit_pass'][:3]}_orb{row['rel_orbit']:03d}_{pol}.tif"


def download_scene(row, out_path: Path, pol, crs, transform, width, height, retries=4):
    image = (
        mask_edge(ee.Image(f"{COLLECTION}/{row['scene_id']}").select(pol))
        .toFloat()
        .unmask(NODATA, False)  # fill masked and out-of-footprint pixels
    )
    params = {
        "bands": [pol],
        "crs": crs,
        "crs_transform": transform,
        "dimensions": f"{width}x{height}",
        "format": "GEO_TIFF",
    }
    for attempt in range(1, retries + 1):
        try:
            url = image.getDownloadURL(params)
            r = requests.get(url, timeout=600)
            r.raise_for_status()
            if not r.content.startswith((b"II*\x00", b"MM\x00*")):
                raise RuntimeError(f"response is not a GeoTIFF: {r.content[:200]!r}")
            tmp = out_path.with_suffix(".tif.part")
            tmp.write_bytes(r.content)
            os.replace(tmp, out_path)
            return
        except Exception as exc:  # noqa: BLE001 - retry on any transient failure
            if attempt == retries:
                raise
            wait = 5 * 2 ** (attempt - 1)
            print(f"  retry {attempt}/{retries - 1} for {out_path.name} in {wait}s: {exc}")
            time.sleep(wait)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", default=os.environ.get("EE_PROJECT"),
                    help="Google Cloud project registered for Earth Engine (default: EE_PROJECT from .env or the environment)")
    ap.add_argument("--aoi", help="GeoJSON study boundary in WGS84 (overrides --bbox)")
    ap.add_argument("--bbox", type=float, nargs=4, metavar=("LON_MIN", "LAT_MIN", "LON_MAX", "LAT_MAX"),
                    help=f"study area bounding box (default {DEFAULT_BBOX})")
    ap.add_argument("--start", default="2023-01-01", help="start date, inclusive")
    ap.add_argument("--end", default="2025-01-01", help="end date, exclusive")
    ap.add_argument("--pol", default="VV", choices=["VV", "VH"])
    ap.add_argument("--orbit-pass", choices=["ASCENDING", "DESCENDING"])
    ap.add_argument("--rel-orbit", type=int, nargs="+", help="relative orbit number(s) to keep")
    ap.add_argument("--allow-partial", action="store_true",
                    help="also keep scenes that only partly cover the study area")
    ap.add_argument("--crs", default="EPSG:27700", help="output CRS (default British National Grid)")
    ap.add_argument("--scale", type=float, default=10.0, help="output pixel size in CRS units (m)")
    ap.add_argument("--out", type=Path, help="output directory (default code/data/s1_<POL>)")
    ap.add_argument("--workers", type=int, default=6, help="parallel downloads")
    ap.add_argument("--dry-run", action="store_true", help="list scenes only, download nothing")
    args = ap.parse_args()

    if not args.project:
        sys.exit("Set EE_PROJECT in .env (see .env.example) or pass --project.")
    ee.Initialize(project=args.project)

    aoi = load_aoi(args.aoi, args.bbox)
    col = build_collection(aoi, args.start, args.end, args.pol,
                           args.orbit_pass, args.rel_orbit, args.allow_partial)
    rows = fetch_metadata(col)
    if not rows:
        sys.exit("No scenes match the filters.")

    print(f"{len(rows)} scenes, {args.start} to {args.end} (end exclusive), {args.pol}, IW")
    for (p, o), n in sorted(Counter((r["orbit_pass"], r["rel_orbit"]) for r in rows).items()):
        print(f"  {p:<10} relative orbit {o:>3}: {n} scenes")

    transform, width, height = fixed_grid(aoi, args.crs, args.scale)
    print(f"Grid: {width} x {height} px at {args.scale:g} m in {args.crs}, origin "
          f"({transform[2]:.0f}, {transform[5]:.0f})")
    if args.dry_run:
        return

    out_dir = args.out or OUT_ROOT / f"s1_{args.pol}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "aoi.geojson").write_text(json.dumps(aoi.getInfo()))
    (out_dir / "grid.json").write_text(json.dumps(
        {"crs": args.crs, "transform": transform, "width": width, "height": height,
         "nodata": NODATA, "units": "dB", "band": args.pol}, indent=2))

    for r in rows:
        r["file"] = scene_filename(r, args.pol)
    todo = [r for r in rows if not (out_dir / r["file"]).exists()]
    print(f"{len(rows) - len(todo)} already downloaded, {len(todo)} to fetch -> {out_dir}")

    failed = set()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(download_scene, r, out_dir / r["file"], args.pol,
                        args.crs, transform, width, height): r
            for r in todo
        }
        for i, fut in enumerate(as_completed(futures), 1):
            r = futures[fut]
            try:
                fut.result()
                print(f"[{i}/{len(todo)}] {r['file']}")
            except Exception as exc:  # noqa: BLE001
                failed.add(r["scene_id"])
                print(f"[{i}/{len(todo)}] FAILED {r['file']}: {exc}")

    with open(out_dir / "index.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[*rows[0].keys(), "downloaded"])
        w.writeheader()
        for r in rows:
            w.writerow({**r, "downloaded": r["scene_id"] not in failed})

    if failed:
        sys.exit(f"{len(failed)} scene(s) failed; re-run to retry them.")
    print("Done.")


if __name__ == "__main__":
    main()
