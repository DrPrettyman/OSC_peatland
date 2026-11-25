#!/usr/bin/env python3
"""Define a treatment zone (Crowdy restoration) and a matched control zone.

Treatment: pixels inside the Crowdy polygon of the Peatland Restoration Register
(works started Mar 2023) that are also inside the moorland-peat mask.

Control: the same number of pixels, chosen from unmasked moor east of the Crowdy
polygon, to match the treatment's peat type and elevation. Eligible pixels are:
  - inside the peat mask (make_mask.py) and on deep peat in the England Peat Map,
    because the treatment is ~95% deep peat ("poor fen" class);
  - at least GAP_M from the Crowdy polygon, so the works themselves (which may
    extend beyond the mapped boundary) don't reach the control;
  - east of the Crowdy polygon's eastern edge;
  - outside every other restoration polygon and outside a POINT_BUFFER_M circle
    around every restoration point record.
The control is grown from a centre inside the largest connected block of eligible
pixels by taking the N nearest eligible pixels (N = treatment size), keeping only
single connected patches. Among all centres, the one whose patch has mean
elevation closest to the treatment's is chosen (ties: nearest to the treatment).
Selection uses only static properties (peat type, elevation, location), never
backscatter, so the comparison isn't tuned to the result.

Writes:
  code/outputs/study_areas.tif      uint8 on the S1 grid: 1 = treatment, 2 = control
  code/outputs/study_areas.geojson  pixel-edge polygons in EPSG:27700 (BNG metres)

    python code/make_study_areas.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import rasterio
from affine import Affine
from rasterio.features import rasterize, shapes
from rasterio.warp import transform_geom
from scipy.ndimage import distance_transform_edt, label

from plot_helpers import get_restoration_areas
from s1stack import load_grid

ROOT = Path(__file__).resolve().parent
ANC = ROOT / "data" / "ancillary"
OUT = ROOT / "outputs"
TREATMENT_SITE = "Crowdy"
GAP_M = 200.0
POINT_BUFFER_M = 1000.0
CENTRE_STEP_PX = 5  # try a control centre every 50 m


def main() -> None:
    grid = load_grid()
    T = Affine(*grid["transform"])
    shape = (grid["height"], grid["width"])

    def burn(geom) -> np.ndarray:
        return rasterize([(geom, 1)], out_shape=shape, transform=T, dtype="uint8").astype(bool)

    with rasterio.open(ANC / "peat_mask.tif") as src:
        keep = src.read(1).astype(bool)
    with rasterio.open(ANC / "dem.tif") as src:
        dem = src.read(1)
    peat = json.loads((ANC / "peat_status.geojson").read_text())
    deep = rasterize([(transform_geom("EPSG:4326", grid["crs"], f["geometry"]), 1)
                      for f in peat["features"]
                      if f["geometry"] and f["properties"]["PSL"].startswith("Deep")],
                     out_shape=shape, transform=T, dtype="uint8").astype(bool)

    rows, cols = np.indices(shape)
    X = T.c + (cols + 0.5) * T.a
    Y = T.f + (rows + 0.5) * T.e

    areas = get_restoration_areas(polygons_only=False)
    site = burn(next(a for a in areas if a["name"] == TREATMENT_SITE)["geometry"])
    treatment = site & keep
    n = int(treatment.sum())

    excluded = np.zeros(shape, bool)
    for a in areas:
        if a["kind"] == "polygon":
            excluded |= burn(a["geometry"])
        else:
            ex, ny = (v * 1000 for v in a["label_xy"])
            excluded |= np.hypot(X - ex, Y - ny) < POINT_BUFFER_M
    gap = distance_transform_edt(~site) * abs(T.a)
    eligible = keep & deep & ~excluded & (gap >= GAP_M) & (X > X[site].max())

    lab, _ = label(eligible)
    sizes = np.bincount(lab.ravel())[1:]
    block = lab == np.argmax(sizes) + 1
    if block.sum() < n:
        raise SystemExit(f"largest eligible block has {block.sum()} px, need {n}")
    br, bc = np.nonzero(block)
    bx, by = X[block], Y[block]
    tx, ty, telev = X[treatment].mean(), Y[treatment].mean(), dem[treatment].mean()

    best = None
    for i in range(0, len(bx), CENTRE_STEP_PX):
        d = np.hypot(bx - bx[i], by - by[i])
        take = np.argpartition(d, n - 1)[:n]
        patch = np.zeros(shape, bool)
        patch[br[take], bc[take]] = True
        if label(patch)[1] != 1:
            continue
        score = (abs(dem[patch].mean() - telev), np.hypot(X[patch].mean() - tx, Y[patch].mean() - ty))
        if best is None or score < best[0]:
            best = (score, patch)
    control = best[1]

    zones = np.zeros(shape, np.uint8)
    zones[treatment] = 1
    zones[control] = 2
    OUT.mkdir(exist_ok=True)
    profile = dict(driver="GTiff", dtype="uint8", count=1, width=shape[1], height=shape[0],
                   crs=grid["crs"], transform=T, compress="deflate", nodata=0)
    with rasterio.open(OUT / "study_areas.tif", "w", **profile) as dst:
        dst.write(zones, 1)

    names = {1: "treatment", 2: "control"}
    feats = []
    for geom, v in shapes(zones, mask=zones > 0, transform=T):
        m = zones == int(v)
        feats.append({"type": "Feature", "geometry": geom, "properties": {
            "zone": names[int(v)],
            "site": TREATMENT_SITE,
            "pixels": int(m.sum()),
            "area_ha": round(m.sum() * abs(T.a * T.e) / 1e4, 2),
            "mean_elev_m": round(float(dem[m].mean()), 1),
            "deep_peat_frac": round(float(deep[m].mean()), 3),
            "centroid_E": round(float(X[m].mean())), "centroid_N": round(float(Y[m].mean())),
        }})
    fc = {"type": "FeatureCollection",
          "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::27700"}},
          "features": feats}
    (OUT / "study_areas.geojson").write_text(json.dumps(fc))

    for f in feats:
        p = f["properties"]
        print(f"{p['zone']:9s} {p['pixels']} px = {p['area_ha']} ha, elev {p['mean_elev_m']} m, "
              f"deep peat {p['deep_peat_frac']:.0%}, centroid E{p['centroid_E']} N{p['centroid_N']}")
    d = np.hypot(X[control].mean() - tx, Y[control].mean() - ty)
    print(f"centroid separation {d:.0f} m; closest approach to {TREATMENT_SITE} polygon "
          f"{gap[control].min():.0f} m")
    print(f"wrote {OUT / 'study_areas.tif'} and {OUT / 'study_areas.geojson'}")


if __name__ == "__main__":
    main()
