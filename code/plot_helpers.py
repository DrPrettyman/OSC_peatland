"""Shared plotting helpers for maps on the Sentinel-1 grid."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.patheffects as pe
import numpy as np
from rasterio.warp import transform_geom

from s1stack import extent, load_grid

ANC = Path(__file__).resolve().parent / "data" / "ancillary"
_HALO = [pe.withStroke(linewidth=2.5, foreground="black")]  # keeps labels legible on any background
KM = [e / 1000 for e in extent()]  # grid extent [xmin, xmax, ymin, ymax] in km (BNG), for imshow


def block_extent_km(k: int) -> list[float]:
    """imshow extent (km) for the grid after s1stack.block_mean(..., k), which trims ragged edges."""
    g = load_grid()
    w, h = g["width"] // k * k, g["height"] // k * k
    px = abs(g["transform"][0]) / 1000
    return [KM[0], KM[0] + w * px, KM[3] - h * px, KM[3]]


def imshow_km(ax, a, ext=KM, **kw):
    """Show a 2-D array on BNG km axes; `ext` overrides the extent (e.g. for 100 m cells)."""
    im = ax.imshow(a, extent=ext, interpolation="nearest", **kw)
    ax.set_xlabel("Easting (km, BNG)")
    ax.set_ylabel("Northing (km, BNG)")
    return im


def get_restoration_areas(polygons_only: bool = True) -> list[dict]:
    """Peatland Restoration Register records in the study box, on the Sentinel-1 grid CRS.

    Reads code/data/ancillary/restoration_register.geojson (from download_peat_map.py).
    Point records are only a grid reference with a nominal 5 m circle, so they are
    dropped unless polygons_only=False.

    Each area is a dict with:
      kind       "polygon" or "point"
      source     short scheme name: "NfC" (Nature for Climate), "EA" (Environment
                 Agency), "CS" (Countryside Stewardship), else the full Src_Data
      name       RestoID, e.g. "Priddicombe"
      start      Act_Date as "YYYY-MM-DD" (None if not recorded)
      ha         recorded habitat area (Hab_Amt)
      land_use   land use before restoration (GHG_LU)
      geometry   GeoJSON geometry in grid CRS metres (for rasterising)
      outlines   list of (x_km, y_km) arrays, one per polygon exterior ring
      label_xy   (easting_km, northing_km) of the record's grid reference
      properties all register fields
    """
    crs = load_grid()["crs"]
    fc = json.loads((ANC / "restoration_register.geojson").read_text())
    areas = []
    for f in fc["features"]:
        p = f["properties"]
        if polygons_only and p["Source_geometry"] != "Polygon":
            continue
        g = transform_geom("EPSG:4326", crs, f["geometry"])
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        areas.append(dict(
            kind="polygon" if p["Source_geometry"] == "Polygon" else "point",
            source=_short_source(p["Src_Data"]),
            name=p["RestoID"], start=p["Act_Date"], ha=p["Hab_Amt"], land_use=p["GHG_LU"],
            geometry=g,
            outlines=[tuple(np.array(poly[0]).T / 1000) for poly in polys],
            label_xy=(p["Easting"] / 1000, p["Northing"] / 1000),
            properties=p,
        ))
    return areas


def _short_source(src: str) -> str:
    for prefix, short in (("Nature for Climate", "NfC"), ("Environment Agency", "EA"),
                          ("Countryside Stewardship", "CS")):
        if src.startswith(prefix):
            return short
    return src


def plot_restoration_areas(ax, areas: list[dict], color: str = "c", point_buffer_km: float | None = 1.0,
                           labels: bool = True) -> None:
    """Overlay restoration register areas (from get_restoration_areas) on a km-axes map.

    Polygons are outlined. Point records are drawn as markers; records sharing a grid
    reference are merged into one marker with a combined label. If point_buffer_km is
    set, a dashed circle of that radius is drawn around each point: the extent of the
    work at a point record is unknown, so the circle marks an area to keep away from
    when choosing a comparison (control) patch.
    """
    for a in areas:
        if a["kind"] != "polygon":
            continue
        for x, y in a["outlines"]:
            ax.plot(x, y, "-", color=color, lw=1.5)
        if labels:
            ax.annotate(f"{a['name']}\n(from {a['start'][:7]})", a["label_xy"],
                        color=color, fontsize=8, ha="center", path_effects=_HALO)

    by_location: dict[tuple, list[dict]] = {}
    for a in areas:
        if a["kind"] == "point":
            by_location.setdefault(a["label_xy"], []).append(a)
    for (x, y), recs in by_location.items():
        ax.plot(x, y, "o", ms=7, mfc="none", mec=color, mew=2)
        if point_buffer_km:
            th = np.linspace(0, 2 * np.pi, 200)
            ax.plot(x + point_buffer_km * np.cos(th), y + point_buffer_km * np.sin(th),
                    "--", color=color, lw=1)
        if labels:
            txt = []
            for src in dict.fromkeys(r["source"] for r in recs):
                rs = [r for r in recs if r["source"] == src]
                ha = sum(r["ha"] for r in rs)
                p = rs[0]["properties"]
                when = (f"from {p['Act_Date'][:4]}" if p["Act_Date"]
                        else f"to {p['EndDate'][:4]}" if p["EndDate"] else "")
                txt.append(f"{src} point, {ha:.0f} ha ({when})")
            ax.annotate("\n".join(txt), (x, y), xytext=(6, -6), textcoords="offset points",
                        color=color, fontsize=7, va="top", path_effects=_HALO)


def get_study_areas() -> dict[str, dict]:
    """Treatment and control zones from make_study_areas.py, keyed by zone name.

    Each zone is a dict with:
      pixels     boolean (height, width) mask on the Sentinel-1 grid (exact selection)
      outlines   list of (x_km, y_km) arrays: exterior rings, then any interior holes
      properties area, elevation, deep-peat fraction, centroid (from the GeoJSON)
    """
    import rasterio  # local import: only needed here

    out_dir = Path(__file__).resolve().parent / "outputs"
    with rasterio.open(out_dir / "study_areas.tif") as src:
        zones = src.read(1)
    fc = json.loads((out_dir / "study_areas.geojson").read_text())
    codes = {"treatment": 1, "control": 2}
    areas: dict[str, dict] = {}
    for f in fc["features"]:
        name = f["properties"]["zone"]
        a = areas.setdefault(name, dict(pixels=zones == codes[name], outlines=[], properties=f["properties"]))
        a["outlines"] += [tuple(np.array(ring).T / 1000) for ring in f["geometry"]["coordinates"]]
    return areas
