"""Chapter 11, diversification: portfolio risk falls with more assets, down to a floor set by correlation.

Assumption: one stable correlation. In practice correlations tend to rise in sell-offs, exactly when
diversification is needed. The check compares the average correlation on the portfolio's worst days with
what a normal market with the same overall correlations would show on its worst days (a parametric
bootstrap, so the selection effect of picking bad days is accounted for).
Baseline beaten: predicting portfolio risk as the average of the assets' risks, which ignores correlation.
"""
from __future__ import annotations

import math

import numpy as np

from .core import ALPHA, BaselineResult, Flag, rng_from
from .synthetic import correlated, equicorrelation

CHAPTER = 11
TITLE = "Diversification"
ASSUMPTION = "stable correlation, also in sell-offs"
BASELINE = "average of the assets' volatilities"


def equal_weight_vol(sigma: float, n: int, rho: float) -> float:
    """Volatility of an equal-weight portfolio of n assets with volatility sigma and pairwise correlation rho."""
    if n < 1:
        raise ValueError("n must be at least 1")
    return sigma * math.sqrt(1 / n + (1 - 1 / n) * rho)


def diversification_floor(sigma: float, rho: float) -> float:
    """Limit of equal_weight_vol as the number of assets grows."""
    return sigma * math.sqrt(rho)


def portfolio_vol(weights, cov) -> float:
    w = np.asarray(weights, dtype=float)
    return float(math.sqrt(max(w @ np.asarray(cov, dtype=float) @ w, 0.0)))


def _avg_offdiag_corr(x: np.ndarray) -> float:
    c = np.corrcoef(x, rowvar=False)
    k = c.shape[0]
    return float((c.sum() - k) / (k * (k - 1)))


def _stress_minus_all(x: np.ndarray, tail: float) -> float:
    port = x.mean(axis=1)
    worst = port <= np.quantile(port, tail)
    return _avg_offdiag_corr(x[worst]) - _avg_offdiag_corr(x)


def check(returns, alpha: float = ALPHA, tail: float = 0.1, sims: int = 199, seed=0) -> list[Flag]:
    """``returns``: one column per asset. Flags when correlation on the worst days is higher than a
    normal market with the same covariance would produce."""
    x = np.asarray(returns, dtype=float)
    if x.ndim != 2 or x.shape[1] < 2 or x.shape[0] < 50:
        raise ValueError("need a (days x assets) array with at least 2 assets and 50 days")
    observed = _stress_minus_all(x, tail)
    rng = rng_from(seed)
    cov = np.cov(x, rowvar=False)
    sd = np.sqrt(np.diag(cov))
    corr = cov / np.outer(sd, sd)
    null = np.array([_stress_minus_all(correlated(x.shape[0], sd, corr, seed=rng), tail) for _ in range(sims)])
    p = float((1 + np.sum(null >= observed)) / (sims + 1))
    detail = f"worst {100 * tail:.0f}% of days: correlation {observed:+.2f} against all days; normal markets " \
             f"show {null.mean():+.2f}"
    return [Flag(CHAPTER, "stable correlation in sell-offs", f"stress correlation, {sims} normal simulations",
                 observed, p, p < alpha, detail)]


def beat_baseline(seed=0, runs: int = 300, k: int = 10, months: int = 120, rho: float = 0.3) -> list[BaselineResult]:
    """Ten equally weighted assets: predict next decade's portfolio volatility from the last decade."""
    rng = rng_from(seed)
    sigma = 0.20 / math.sqrt(12)
    corr = equicorrelation(k, rho)
    e_f, e_b = [], []
    for _ in range(runs):
        past = correlated(months, np.full(k, sigma), corr, seed=rng)
        future = correlated(months, np.full(k, sigma), corr, seed=rng)
        realized = float(future.mean(axis=1).std(ddof=1))
        s_hat = float(past.std(axis=0, ddof=1).mean())
        predicted = equal_weight_vol(s_hat, k, _avg_offdiag_corr(past))
        e_f.append(abs(predicted - realized))
        e_b.append(abs(s_hat - realized))
    a, b = np.array(e_f), np.array(e_b)
    return [BaselineResult(CHAPTER, "diversification formula", BASELINE,
                           "absolute error of next decade's monthly portfolio volatility", float(a.mean()),
                           float(b.mean()), wins=float(np.mean(a < b)),
                           note=f"{runs} runs, {k} assets, correlation {rho}")]
