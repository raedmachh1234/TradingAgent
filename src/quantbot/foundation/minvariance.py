"""Chapter 12, the minimum-variance mix: the calmest combination of assets.

Assumption: the covariance matrix is known. It is estimated, and minimum-variance weights are sensitive to
estimation error, especially with few observations per asset. The check bootstraps the weights and flags
them as unstable when they swing too much between resamples; ``ledoit_wolf`` shrinks the estimate.
Baseline beaten: equal weights (1/N), measured by realized out-of-sample volatility.
"""
from __future__ import annotations

import math

import numpy as np
from scipy.optimize import minimize

from .core import BaselineResult, Flag, rng_from
from .synthetic import correlated

CHAPTER = 12
TITLE = "Minimum variance"
ASSUMPTION = "known covariance matrix"
BASELINE = "equal weights (1/N)"
# Rule of thumb: the mix is unstable when a typical weight moves between bootstrap resamples by more than half
# of an equal weight (1/N).
UNSTABLE_RELATIVE_SD = 0.5


def two_asset_weight(s1: float, s2: float, rho: float) -> float:
    """Weight of asset 1 in the minimum-variance mix of two assets."""
    denom = s1 * s1 + s2 * s2 - 2 * rho * s1 * s2
    if denom <= 0:
        raise ValueError("the two assets are identical; any mix has the same variance")
    return (s2 * s2 - rho * s1 * s2) / denom


def two_asset_vol(w1: float, s1: float, s2: float, rho: float) -> float:
    var = w1 * w1 * s1 * s1 + (1 - w1) ** 2 * s2 * s2 + 2 * w1 * (1 - w1) * rho * s1 * s2
    return math.sqrt(max(var, 0.0))


def min_variance_weights(cov, long_only: bool = True, max_weight: float = 1.0) -> np.ndarray:
    """Fully invested minimum-variance weights; closed form when unconstrained, SLSQP otherwise."""
    c = np.asarray(cov, dtype=float)
    k = c.shape[0]
    if max_weight * k < 1 - 1e-12:
        raise ValueError("max_weight too small to be fully invested")
    if not long_only and max_weight >= 1:
        w = np.linalg.solve(c, np.ones(k))
        return w / w.sum()
    lo = 0.0 if long_only else -1.0
    res = minimize(lambda w: w @ c @ w, np.full(k, 1.0 / k), jac=lambda w: 2 * c @ w, method="SLSQP",
                   bounds=[(lo, max_weight)] * k,
                   constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1, "jac": lambda w: np.ones(k)}],
                   options={"ftol": 1e-14, "maxiter": 500})
    if not res.success:
        raise RuntimeError(f"minimum-variance optimisation failed: {res.message}")
    w = np.clip(res.x, lo, max_weight)
    return w / w.sum()


def ledoit_wolf(returns) -> tuple[np.ndarray, float]:
    """Ledoit-Wolf (2004) shrinkage towards a scaled identity. Returns (covariance, shrinkage in [0, 1])."""
    x = np.asarray(returns, dtype=float)
    t, k = x.shape
    x = x - x.mean(axis=0)
    s = x.T @ x / t
    mu = np.trace(s) / k
    d2 = float(np.sum((s - mu * np.eye(k)) ** 2)) / k
    # sum_t ||x_t x_t' - S||^2 = sum_t ||x_t||^4 - t ||S||^2
    b2 = (float(np.sum(np.sum(x * x, axis=1) ** 2)) - t * float(np.sum(s * s))) / k / t**2
    shrink = 0.0 if d2 == 0 else min(b2, d2) / d2
    return shrink * mu * np.eye(k) + (1 - shrink) * s, shrink


def check(returns, max_weight: float = 1.0, resamples: int = 200, seed=0) -> list[Flag]:
    """Bootstrap the minimum-variance weights; flag when they are too unstable to trust."""
    x = np.asarray(returns, dtype=float)
    rng = rng_from(seed)
    t = x.shape[0]
    ws = np.array([min_variance_weights(np.cov(x[rng.integers(0, t, t)], rowvar=False), True, max_weight)
                   for _ in range(resamples)])
    sd = float(ws.std(axis=0).mean())
    relative = sd * x.shape[1]
    return [Flag(CHAPTER, "covariance known well enough", f"bootstrap of weights, {resamples} resamples",
                 relative, None, relative > UNSTABLE_RELATIVE_SD,
                 f"a weight moves by {sd:.3f} between resamples, {100 * relative:.0f}% of an equal weight; "
                 f"{t} observations for {x.shape[1]} assets")]


def beat_baseline(seed=0, runs: int = 8, months: int = 420, window: int = 60,
                  every: int = 3) -> list[BaselineResult]:
    """Five asset classes with different risks, rebalanced every quarter, long only, at most 40% each:
    out-of-sample volatility of the Ledoit-Wolf minimum-variance mix against equal weights."""
    rng = rng_from(seed)
    vols = np.array([0.05, 0.07, 0.12, 0.16, 0.20]) / math.sqrt(12)
    corr = np.array([[1.0, 0.6, 0.2, 0.0, 0.1],
                     [0.6, 1.0, 0.4, 0.3, 0.2],
                     [0.2, 0.4, 1.0, 0.7, 0.4],
                     [0.0, 0.3, 0.7, 1.0, 0.5],
                     [0.1, 0.2, 0.4, 0.5, 1.0]])
    v_mv, v_eq = [], []
    for _ in range(runs):
        r = correlated(months, vols, corr, df=5, seed=rng)
        out_mv, out_eq = [], []
        for t in range(window, months, every):
            cov, _ = ledoit_wolf(r[t - window:t])
            w = min_variance_weights(cov, True, 0.4)
            held = r[t:t + every]
            out_mv.extend(held @ w)
            out_eq.extend(held.mean(axis=1))
        v_mv.append(np.std(out_mv, ddof=1) * math.sqrt(12))
        v_eq.append(np.std(out_eq, ddof=1) * math.sqrt(12))
    a, b = np.array(v_mv), np.array(v_eq)
    return [BaselineResult(CHAPTER, "minimum variance, Ledoit-Wolf covariance", BASELINE,
                           "realized out-of-sample yearly volatility", float(a.mean()), float(b.mean()),
                           wins=float(np.mean(a < b)),
                           note=f"{runs} runs of {months} months, 5-year window, quarterly rebalancing, "
                                f"fat-tailed (t5) returns")]
