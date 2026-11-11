"""Chapter 13, beta and CAPM: how much an asset moves with the market, and the return CAPM expects for it.

Assumption: one stable, linear beta. The check estimates beta on each half of the sample and tests whether
the two differ; a beta that drifts makes hedges and CAPM expectations wrong.
Baseline beaten: hedging an asset one-for-one with the market (beta taken as 1).
"""
from __future__ import annotations

import math

import numpy as np
from scipy import stats

from .core import ALPHA, BaselineResult, Flag, as_array, rng_from

CHAPTER = 13
TITLE = "Beta and CAPM"
ASSUMPTION = "stable linear beta"
BASELINE = "hedge one-for-one (beta = 1)"


def beta_from_correlation(rho: float, sigma_i: float, sigma_m: float) -> float:
    if sigma_m <= 0:
        raise ValueError("market volatility must be positive")
    return rho * sigma_i / sigma_m


def beta(asset, market) -> float:
    a, m = as_array(asset), as_array(market)
    if a.size != m.size:
        raise ValueError("series must have the same length")
    mc = m - m.mean()
    return float(np.sum((a - a.mean()) * mc) / np.sum(mc * mc))


def _beta_se(a: np.ndarray, m: np.ndarray) -> tuple[float, float]:
    b = beta(a, m)
    resid = (a - a.mean()) - b * (m - m.mean())
    se = math.sqrt(float(resid @ resid) / (a.size - 2) / float(np.sum((m - m.mean()) ** 2)))
    return b, se


def expected_move(beta_value: float, market_move: float) -> float:
    return beta_value * market_move


def capm_expected_return(rf: float, beta_value: float, market_return: float) -> float:
    return rf + beta_value * (market_return - rf)


def check(asset, market, alpha: float = ALPHA) -> list[Flag]:
    a, m = as_array(asset, min_size=20), as_array(market, min_size=20)
    half = a.size // 2
    b1, se1 = _beta_se(a[:half], m[:half])
    b2, se2 = _beta_se(a[half:], m[half:])
    z = (b1 - b2) / math.sqrt(se1**2 + se2**2)
    p = float(2 * stats.norm.sf(abs(z)))
    return [Flag(CHAPTER, "stable beta", "first half against second half", z, p, p < alpha,
                 f"beta {b1:.2f} then {b2:.2f}")]


def beat_baseline(seed=0, runs: int = 300, days: int = 250, true_beta: float = 1.4) -> list[BaselineResult]:
    """Estimate beta on one year, hedge the next year: variance left after each hedge."""
    rng = rng_from(seed)
    r_est, r_one = [], []
    for _ in range(runs):
        m = 0.01 * rng.standard_normal(2 * days)
        a = true_beta * m + 0.008 * rng.standard_normal(2 * days)
        b_hat = beta(a[:days], m[:days])
        r_est.append(np.var(a[days:] - b_hat * m[days:]))
        r_one.append(np.var(a[days:] - m[days:]))
    x, y = np.array(r_est), np.array(r_one)
    return [BaselineResult(CHAPTER, "hedge with the estimated beta", BASELINE,
                           "variance of the hedged position next year (x 1e5)", float(x.mean() * 1e5),
                           float(y.mean() * 1e5), wins=float(np.mean(x < y)),
                           note=f"{runs} runs, true beta {true_beta}")]
