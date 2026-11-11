"""Chapter 7, volatility: the standard deviation of returns, and how to annualise it.

The book divides by N (the population formula); ``volatility`` follows it by default and takes ``ddof=1``
for the sample formula.
Assumption: one constant volatility. Real markets alternate calm and wild periods; the check is the
McLeod-Li test for that clustering, and ``ewma_variance`` follows a changing volatility.
Baseline beaten: forecasting tomorrow's risk with the long-run average, on data whose volatility clusters.
"""
from __future__ import annotations

import math

import numpy as np

from .core import ALPHA, BaselineResult, Flag, as_array, clustering_flag, rng_from
from .synthetic import garch_t

CHAPTER = 7
TITLE = "Volatility"
ASSUMPTION = "constant volatility"
BASELINE = "long-run average variance as tomorrow's forecast"


def mean(returns) -> float:
    return float(as_array(returns, min_size=1).mean())


def volatility(returns, ddof: int = 0) -> float:
    return float(as_array(returns, min_size=ddof + 1).std(ddof=ddof))


def annualize(vol: float, periods: int = 252) -> float:
    return vol * math.sqrt(periods)


def ewma_variance(returns, lam: float = 0.94, init: float | None = None) -> np.ndarray:
    """One-step-ahead variance forecasts: out[t] uses returns up to t - 1 (RiskMetrics weighting)."""
    if not 0 < lam < 1:
        raise ValueError("lam must be in (0, 1)")
    r = as_array(returns, min_size=2)
    out = np.empty(r.size)
    v = float(np.var(r[: min(20, r.size)])) if init is None else init
    for t in range(r.size):
        out[t] = v
        v = lam * v + (1 - lam) * r[t] ** 2
    return out


def check(returns, alpha: float = ALPHA, lags: int = 10) -> list[Flag]:
    return [clustering_flag(CHAPTER, returns, lags, alpha)]


def _qlike(forecast: np.ndarray, truth: np.ndarray) -> float:
    ratio = truth / forecast
    return float(np.mean(ratio - np.log(ratio) - 1))


def beat_baseline(seed=0, runs: int = 20, days: int = 3000, warmup: int = 250) -> list[BaselineResult]:
    """Next-day variance forecasts on GARCH data with fat tails, scored against the true variance."""
    rng = rng_from(seed)
    l_ewma, l_avg = [], []
    for _ in range(runs):
        r, h = garch_t(days, sigma=0.01, alpha=0.08, beta=0.9, df=5, seed=rng)
        ewma = ewma_variance(r, init=float(np.var(r[:warmup])))
        csum = np.cumsum(r**2)
        expanding = csum[:-1] / np.arange(1, days)  # mean of r^2 up to t - 1, forecast for t
        l_ewma.append(_qlike(ewma[warmup:], h[warmup:]))
        l_avg.append(_qlike(expanding[warmup - 1:], h[warmup:]))
    a, b = np.array(l_ewma), np.array(l_avg)
    return [BaselineResult(CHAPTER, "EWMA variance (lambda 0.94)", BASELINE,
                           "QLIKE loss against the true daily variance", float(a.mean()), float(b.mean()),
                           wins=float(np.mean(a < b)), note=f"{runs} GARCH runs of {days} days, t(5) shocks")]
