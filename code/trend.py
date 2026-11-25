"""Per-cell trend + annual harmonic regression, vectorised over a (time, y, x) stack.

Model for each cell:

    y(t) = b0 + b1 (t - t0) + g1 sin(2 pi t) + g2 cos(2 pi t) + e(t),   t in years

b1 is the trend in dB/yr. Standard errors are inflated for lag-1 autocorrelation of
the residuals (effective sample size n_eff = n (1 - rho) / (1 + rho)), because
consecutive 12-day acquisitions share weather.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

T0 = 2024.0  # centre of Jan 2023 - Dec 2024, so b0 is the level at the midpoint


def design(t_years: np.ndarray, t0: float = T0) -> np.ndarray:
    w = 2 * np.pi * t_years
    return np.column_stack([np.ones_like(t_years), t_years - t0, np.sin(w), np.cos(w)])


@dataclass
class Fit:
    beta: np.ndarray      # (4, h, w): b0, b1 (dB/yr), g1, g2
    se_naive: np.ndarray  # (h, w) OLS slope SE assuming independent residuals
    se: np.ndarray        # (h, w) slope SE inflated for AR(1) residuals
    rho: np.ndarray       # (h, w) lag-1 autocorrelation of residuals
    resid_std: np.ndarray
    n: np.ndarray         # (h, w) number of valid dates

    @property
    def slope(self) -> np.ndarray:
        return self.beta[1]

    @property
    def t(self) -> np.ndarray:
        return self.beta[1] / self.se

    @property
    def amplitude(self) -> np.ndarray:
        return np.hypot(self.beta[2], self.beta[3])


def fit_cells(t_years: np.ndarray, Y: np.ndarray, min_frac: float = 0.8) -> Fit:
    """OLS per cell of Y (n, h, w) on design(t_years); NaNs are treated as missing."""
    X = design(t_years)
    n, h, w = Y.shape
    p = X.shape[1]
    y = Y.reshape(n, -1)
    m = np.isfinite(y)
    ok = m.mean(0) >= min_frac
    yk, mk = y[:, ok], m[:, ok]
    y0 = np.where(mk, yk, 0.0)
    XtX = np.einsum("np,nq,nk->kpq", X, X, mk.astype(float))
    inv = np.linalg.inv(XtX)
    b = np.einsum("kpq,kq->kp", inv, np.einsum("np,nk->kp", X, y0))
    r = np.where(mk, yk - X @ b.T, np.nan)
    nk = mk.sum(0)
    s2 = np.nansum(r**2, 0) / (nk - p)
    se_naive = np.sqrt(s2 * inv[:, 1, 1])
    # lag-1 autocorrelation over consecutive valid acquisitions
    r0 = np.nan_to_num(r)
    pair = mk[1:] & mk[:-1]
    rho = (r0[1:] * r0[:-1] * pair).sum(0) / np.maximum((r0**2).sum(0), 1e-12) * nk / np.maximum(pair.sum(0), 1)
    rho = np.clip(rho, 0.0, 0.9)
    n_eff = nk * (1 - rho) / (1 + rho)
    se = se_naive * np.sqrt((nk - p) / np.maximum(n_eff - p, 1.0))

    def put(v, lead=()):
        out = np.full((*lead, h * w), np.nan)
        out[..., ok] = v
        return out.reshape(*lead, h, w)

    return Fit(beta=put(b.T, (p,)), se_naive=put(se_naive), se=put(se), rho=put(rho),
               resid_std=put(np.sqrt(s2)), n=put(nk))


def fit_series(t_years: np.ndarray, y: np.ndarray, min_frac: float = 0.8) -> Fit:
    """fit_cells for a single time series. beta has shape (4,); other fields are floats."""
    f = fit_cells(t_years, np.asarray(y, float)[:, None, None], min_frac)
    return Fit(beta=f.beta[:, 0, 0], se_naive=float(f.se_naive[0, 0]), se=float(f.se[0, 0]),
               rho=float(f.rho[0, 0]), resid_std=float(f.resid_std[0, 0]), n=float(f.n[0, 0]))
