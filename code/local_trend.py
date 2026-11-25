#!/usr/bin/env python3
"""Write the 100 m trend map for one orbit (default 103) as a GeoTIFF.

Same method as the notebook (eda.ipynb, "Subtracting the moor-wide signal"):
  1. mask to moorland peat (data/ancillary/peat_mask.tif, from make_mask.py);
  2. moor-wide signal R(t): median VV over all masked 10 m pixels on each date;
  3. average masked pixels into 100 m cells (cells need >= MIN_COVER masked pixels);
  4. fit trend + annual cycle (trend.fit_cells) to each cell, both raw and with R(t)
     subtracted. The local slope is the trend relative to the moor as a whole.

Writes outputs/local_trend_orb{orbit:03d}.tif (100 m, EPSG:27700), float32 bands:
  local_slope_dB_per_yr, local_se, local_t, raw_slope_dB_per_yr, raw_se, seasonal_amp_dB
(SEs are inflated for lag-1 autocorrelation; NaN outside the mask.)

    python local_trend.py [--orbit 103]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import rasterio
from affine import Affine

from s1stack import block_mean, decimal_year, load_grid, load_stack
from trend import fit_cells

ROOT = Path(__file__).resolve().parent
ANC = ROOT / "data" / "ancillary"
OUT = ROOT / "outputs"
K = 10           # 10 x 10 pixels -> 100 m cells
MIN_COVER = 0.5  # fraction of a cell's pixels that must be in the mask


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--orbit", type=int, default=103)
    orbit = ap.parse_args().orbit

    with rasterio.open(ANC / "peat_mask.tif") as src:
        keep = src.read(1).astype(bool)
    cell_ok = block_mean(keep[None].astype(float), K)[0] >= MIN_COVER

    idx, stack = load_stack(orbit)
    ty = decimal_year(idx.time)
    moor = np.nanmedian(stack[:, keep], axis=1)
    cells = block_mean(np.where(keep, stack, np.nan), K)
    cells[:, ~cell_ok] = np.nan
    raw = fit_cells(ty, cells)
    local = fit_cells(ty, cells - moor[:, None, None])

    bands = {"local_slope_dB_per_yr": local.slope, "local_se": local.se, "local_t": local.t,
             "raw_slope_dB_per_yr": raw.slope, "raw_se": raw.se, "seasonal_amp_dB": raw.amplitude}
    grid = load_grid()
    px, _, x0, _, py, y0 = grid["transform"]
    h, w = cell_ok.shape
    profile = dict(driver="GTiff", dtype="float32", count=len(bands), width=w, height=h, crs=grid["crs"],
                   transform=Affine(px * K, 0, x0, 0, py * K, y0), nodata=np.nan, compress="deflate")
    OUT.mkdir(exist_ok=True)
    path = OUT / f"local_trend_orb{orbit:03d}.tif"
    with rasterio.open(path, "w", **profile) as dst:
        for i, (name, a) in enumerate(bands.items(), 1):
            dst.write(a.astype("float32"), i)
            dst.set_band_description(i, name)

    s = local.slope[cell_ok]
    print(f"orbit {orbit}: {cell_ok.sum()} of {cell_ok.size} 100 m cells; local slope 5-95% "
          f"[{np.nanpercentile(s, 5):+.2f}, {np.nanpercentile(s, 95):+.2f}] dB/yr; "
          f"|t| > 2 in {np.nanmean(np.abs(local.t[cell_ok]) > 2):.1%} of cells")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
