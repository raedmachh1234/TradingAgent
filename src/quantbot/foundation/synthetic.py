"""Synthetic markets with a known truth, used to show where each chapter's assumptions hold and where they
break, and to measure every method against its baseline. These are not market data and say nothing about
any real asset."""
from __future__ import annotations

import numpy as np
from scipy.signal import lfilter

from .core import rng_from


def iid_normal(n: int, sigma: float = 0.01, mu: float = 0.0, seed=None) -> np.ndarray:
    """Independent normal returns: every assumption in the book holds."""
    return mu + sigma * rng_from(seed).standard_normal(n)


def student_t(n: int, df: float, sigma: float = 0.01, mu: float = 0.0, seed=None) -> np.ndarray:
    """Independent fat-tailed returns, Student t scaled to standard deviation ``sigma`` (needs df > 2)."""
    if df <= 2:
        raise ValueError("df must exceed 2 for a finite variance")
    return mu + sigma * np.sqrt((df - 2) / df) * rng_from(seed).standard_t(df, n)


def ar1(n: int, phi: float, sigma: float = 0.01, mu: float = 0.0, seed=None) -> np.ndarray:
    """Autocorrelated returns x_t = mu + phi (x_{t-1} - mu) + e_t with unconditional sd ``sigma``.
    phi > 0 is momentum, phi < 0 is mean reversion; independence fails either way."""
    if not -1 < phi < 1:
        raise ValueError("phi must be inside (-1, 1)")
    rng = rng_from(seed)
    e = sigma * np.sqrt(1 - phi**2) * rng.standard_normal(n)
    start = sigma * rng.standard_normal()  # a draw from the stationary distribution
    x, _ = lfilter([1.0], [1.0, -phi], e, zi=[phi * start])
    return mu + x


def garch_t(n: int, sigma: float = 0.01, alpha: float = 0.08, beta: float = 0.9, df: float = 5.0,
            mu: float = 0.0, seed=None, burn: int = 500) -> tuple[np.ndarray, np.ndarray]:
    """GARCH(1,1) returns with Student-t shocks: volatility clusters and tails are fat, yet the returns
    themselves are uncorrelated. Returns (returns, true conditional variance of each return)."""
    if alpha + beta >= 1:
        raise ValueError("alpha + beta must be below 1")
    rng = rng_from(seed)
    omega = sigma**2 * (1 - alpha - beta)
    z = np.sqrt((df - 2) / df) * rng.standard_t(df, n + burn)
    h = np.empty(n + burn)
    r = np.empty(n + burn)
    h_t = sigma**2
    for t in range(n + burn):
        h[t] = h_t
        r[t] = np.sqrt(h_t) * z[t]
        h_t = omega + alpha * r[t] ** 2 + beta * h_t
    return mu + r[burn:], h[burn:]


def correlated(n: int, vols, corr, mu=None, df: float | None = None, seed=None) -> np.ndarray:
    """n draws of len(vols) correlated returns: normal, or multivariate Student t with ``df`` degrees of
    freedom scaled so that ``vols`` are the standard deviations."""
    vols = np.asarray(vols, dtype=float)
    corr = np.asarray(corr, dtype=float)
    rng = rng_from(seed)
    chol = np.linalg.cholesky(corr)
    z = rng.standard_normal((n, vols.size)) @ chol.T
    if df is not None:
        if df <= 2:
            raise ValueError("df must exceed 2")
        z = z * np.sqrt((df - 2) / rng.chisquare(df, (n, 1)))
    out = z * vols
    return out if mu is None else out + np.asarray(mu, dtype=float)


def equicorrelation(k: int, rho: float) -> np.ndarray:
    return np.full((k, k), rho) + (1 - rho) * np.eye(k)


def regime_correlated(n: int, k: int, calm_rho: float = 0.1, crisis_rho: float = 0.8,
                      crisis_share: float = 0.15, crisis_vol_mult: float = 2.5, sigma: float = 0.01,
                      seed=None) -> np.ndarray:
    """k assets whose correlation jumps in a minority of high-volatility days: diversification works in calm
    markets and fails in the crashes it is needed for."""
    rng = rng_from(seed)
    crisis = rng.random(n) < crisis_share
    calm = correlated(n, np.full(k, sigma), equicorrelation(k, calm_rho), seed=rng)
    wild = correlated(n, np.full(k, sigma * crisis_vol_mult), equicorrelation(k, crisis_rho), seed=rng)
    return np.where(crisis[:, None], wild, calm)
