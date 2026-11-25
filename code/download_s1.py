#!/usr/bin/env python3
"""Download Sentinel-1 GRD backscatter scenes over Bodmin Moor from Google Earth Engine.

Every satellite pass in the date range that covers the study area is exported
as a single-band GeoTIFF (sigma0 in dB) on one fixed grid, so the files stack
pixel-for-pixel for time-series and per-pixel trend analysis. An index.csv
records each pass's acquisition time, platform, orbit pass and relative orbit,
so the analysis can restrict itself to a single viewing geometry.

Earth Engine stores each pass as consecutive ~25 s slices (scenes). Where the
study area straddles a slice boundary (e.g. ascending relative orbit 1 over
Bodmin Moor), the slices of that pass are grouped by platform and absolute
orbit number and mosaicked into one image. A pass is kept if its combined
footprint covers at least --min-coverage of the study area. Earth Engine's
slices leave a 1-2 pixel gap of no data at their shared boundary; it is kept as
nodata rather than interpolated (~0.1% of pixels, position varies by date).

Data: COPERNICUS/S1_GRD (IW mode). Earth Engine has already applied thermal
noise removal, radiometric calibration, terrain correction (SRTM 30 m) and
conversion to dB. The edge mask below removes low-value border noise (< -30 dB).

Usage
-----
    # once per machine (localhost mode avoids gcloud; see README)
    earthengine authenticate --auth_mode=localhost

    # list the matching passes and per-orbit counts without downloading
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


def build_collection(aoi, start, end, pol, orbit_pass, rel_orbits):
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
    return col.sort("system:time_start")


def fetch_metadata(col: ee.ImageCollection) -> list[dict]:
    """Return one dict per scene (slice)."""
    props = [
        "system:index",
        "system:time_start",
        "platform_number",
        "orbitProperties_pass",
        "relativeOrbitNumber_start",
        "orbitNumber_start",
        "resolution_meters",
    ]
    cols = ee.Dictionary({p: col.aggregate_array(p) for p in props}).getInfo()
    
    if cols is None:
        return []
    
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
                "abs_orbit": int(cols["orbitNumber_start"][i]),
                "resolution_m": cols["resolution_meters"][i],
            }
        )
    return rows


def group_passes(scenes: list[dict], col: ee.ImageCollection, aoi: ee.Geometry) -> list[dict]:
    """Group slices of the same pass and compute each pass's coverage of the AOI.

    Slices from one pass share the platform and absolute orbit number.
    """
    groups: dict[tuple, list[dict]] = {}
    for sc in scenes:
        groups.setdefault((sc["platform"], sc["abs_orbit"]), []).append(sc)

    passes = []
    for members in groups.values():
        members.sort(key=lambda m: m["datetime_utc"])
        first = members[0]
        passes.append({
            "datetime_utc": first["datetime_utc"],
            "platform": first["platform"],
            "orbit_pass": first["orbit_pass"],
            "rel_orbit": first["rel_orbit"],
            "abs_orbit": first["abs_orbit"],
            "resolution_m": first["resolution_m"],
            "n_slices": len(members),
            "scene_ids": ";".join(m["scene_id"] for m in members),
        })
    passes.sort(key=lambda p: p["datetime_utc"])

    # Fraction of the AOI inside the union of each pass's slice footprints.
    aoi_area = aoi.area(1)

    def coverage(ids):
        footprint = col.filter(ee.Filter.inList("system:index", ids)).geometry().dissolve(1)
        return footprint.intersection(aoi, 1).area(1).divide(aoi_area)

    id_lists = ee.List([p["scene_ids"].split(";") for p in passes])
    for p, c in zip(passes, id_lists.map(coverage).getInfo()):
        p["coverage"] = round(c, 4)
    return passes


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


def download_pass(row, out_path: Path, pol, crs, transform, width, height, retries=4):
    # Edge-mask each slice first so its neighbour fills the masked border.
    slices = [mask_edge(ee.Image(f"{COLLECTION}/{sid}").select(pol))
              for sid in row["scene_ids"].split(";")]
    image = slices[0] if len(slices) == 1 else ee.ImageCollection(slices).mosaic()
    image = (
        image
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


def _by_orbit(rows: list[dict]) -> dict[tuple, list[dict]]:
    out: dict[tuple, list[dict]] = {}
    for r in rows:
        out.setdefault((r["orbit_pass"], r["rel_orbit"]), []).append(r)
    return out


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
    ap.add_argument("--min-coverage", type=float, default=0.99,
                    help="minimum fraction of the study area a pass (after mosaicking its "
                         "slices) must cover to be kept (default 0.99; 0 keeps all)")
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
                           args.orbit_pass, args.rel_orbit)
    scenes = fetch_metadata(col)
    if not scenes:
        sys.exit("No scenes match the filters.")

    passes = group_passes(scenes, col, aoi)
    rows = [p for p in passes if p["coverage"] >= args.min_coverage]
    dropped = len(passes) - len(rows)

    print(f"{len(scenes)} scenes in {len(passes)} passes intersect the study area, "
          f"{args.start} to {args.end} (end exclusive), {args.pol}, IW")
    print(f"{len(rows)} passes cover >= {args.min_coverage:.0%} of it"
          + (f" ({dropped} dropped)" if dropped else "") + ":")
    for (p, o), grp in sorted(_by_orbit(rows).items()):
        mosaicked = sum(r["n_slices"] > 1 for r in grp)
        print(f"  {p:<10} relative orbit {o:>3}: {len(grp)} passes"
              + (f" ({mosaicked} mosaicked from 2+ slices)" if mosaicked else ""))
    if not rows:
        sys.exit("No passes meet the coverage threshold.")

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
            pool.submit(download_pass, r, out_dir / r["file"], args.pol,
                        args.crs, transform, width, height): r
            for r in todo
        }
        for i, fut in enumerate(as_completed(futures), 1):
            r = futures[fut]
            try:
                fut.result()
                print(f"[{i}/{len(todo)}] {r['file']}")
            except Exception as exc:  # noqa: BLE001
                failed.add(r["file"])
                print(f"[{i}/{len(todo)}] FAILED {r['file']}: {exc}")

    with open(out_dir / "index.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[*rows[0].keys(), "downloaded"])
        w.writeheader()
        for r in rows:
            w.writerow({**r, "downloaded": r["file"] not in failed})

    if failed:
        sys.exit(f"{len(failed)} pass(es) failed; re-run to retry them.")
    print("Done.")


if __name__ == "__main__":
    main()
