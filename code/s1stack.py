"""Load the downloaded Sentinel-1 VV GeoTIFFs into a (time, y, x) stack.

All files share one grid (see code/data/s1_VV/grid.json), so they stack directly.
The GeoTIFFs carry no nodata tag; the fill value -9999 is masked to NaN here.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio

DATA_DIR = Path(__file__).resolve().parent / "data" / "s1_VV"
NODATA = -9999.0


def load_index(data_dir: Path = DATA_DIR) -> pd.DataFrame:
    idx = pd.read_csv(data_dir / "index.csv", parse_dates=["datetime_utc"])
    idx = idx[idx.downloaded].sort_values("datetime_utc").reset_index(drop=True)
    idx["time"] = idx.datetime_utc.dt.tz_localize(None)
    return idx


def load_grid(data_dir: Path = DATA_DIR) -> dict:
    return json.loads((data_dir / "grid.json").read_text())


def load_stack(orbit: int | None = None, data_dir: Path = DATA_DIR):
    """Return (index, stack) for one relative orbit (or all if None).

    stack is float32 (n_dates, height, width) in dB, NaN where no data.
    """
    idx = load_index(data_dir)
    if orbit is not None:
        idx = idx[idx.rel_orbit == orbit].reset_index(drop=True)
    g = load_grid(data_dir)
    stack = np.empty((len(idx), g["height"], g["width"]), dtype=np.float32)
    for i, f in enumerate(idx.file):
        with rasterio.open(data_dir / f) as src:
            a = src.read(1)
        a[a <= NODATA + 1] = np.nan
        stack[i] = a
    return idx, stack


def load_stacks(orbits: Iterable[int], data_dir: Path = DATA_DIR):
    """Load several orbits; return (idxs, stacks) as dicts keyed by orbit number.

    `orbits` can be any iterable of relative orbit numbers, including a dict
    such as {103: "label", ...} (its keys are used).
    """
    idxs, stacks = {}, {}
    for o in orbits:
        idxs[o], stacks[o] = load_stack(o, data_dir)
    return idxs, stacks


def extent(data_dir: Path = DATA_DIR) -> list[float]:
    """[xmin, xmax, ymin, ymax] in BNG metres, for imshow(extent=...)."""
    g = load_grid(data_dir)
    px, _, x0, _, py, y1 = g["transform"]
    return [x0, x0 + px * g["width"], y1 + py * g["height"], y1]


def decimal_year(t: pd.Series) -> np.ndarray:
    t = pd.DatetimeIndex(t)
    start = pd.DatetimeIndex([pd.Timestamp(y, 1, 1) for y in t.year])
    end = pd.DatetimeIndex([pd.Timestamp(y + 1, 1, 1) for y in t.year])
    return np.asarray(t.year + (t - start) / (end - start))


def block_mean(a: np.ndarray, k: int) -> np.ndarray:
    """Mean over k x k blocks of the last two axes (trims the ragged edge), NaN-aware.

    Averaging in dB is a geometric mean of linear power; for speckle reduction it is
    standard practice, but note it differs slightly from averaging linear sigma0.
    """
    *lead, h, w = a.shape
    h2, w2 = h // k * k, w // k * k
    a = a[..., :h2, :w2].reshape(*lead, h2 // k, k, w2 // k, k)
    return np.nanmean(a, axis=(-3, -1))
