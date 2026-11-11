"""Chapter 10, correlation: how two returns move together.

Assumptions: Pearson correlation measures linear co-movement and is reliable when returns are roughly
normal. Two things break it: fat tails, which make the estimate noisy, and dependence that is not linear,
such as the book's Y = X^2 with zero correlation. The check flags both: Jarque-Bera on each series, and a
significant correlation between the sizes of the moves when the moves themselves look uncorrelated.
Baseline beaten: the Pearson estimate itself on fat-tailed data, against sin(pi * tau / 2) from Kendall's tau.
"""
from __future__ import annotations

import math

import numpy as np
from scipy import stats

from .core import ALPHA, BaselineResult, Flag, as_array, normality_flag, rng_from
from .synthetic import correlated

CHAPTER = 10
TITLE = "Correlation"
ASSUMPTION = "linear dependence, normal returns"
BASELINE = "Pearson correlation on fat-tailed data"


def covariance(x, y, ddof: int = 0) -> float:
    a, b = as_array(x, min_size=2), as_array(y, min_size=2)
    if a.size != b.size:
        raise ValueError("series must have the same length")
    return float(np.sum((a - a.mean()) * (b - b.mean())) / (a.size - ddof))


def correlation_from_cov(cov: float, sx: float, sy: float) -> float:
    if sx <= 0 or sy <= 0:
        raise ValueError("volatilities must be positive")
    return cov / (sx * sy)


def pearson(x, y) -> float:
    a, b = as_array(x), as_array(y)
    return float(np.corrcoef(a, b)[0, 1])


def robust_correlation(x, y) -> float:
    """sin(pi * tau / 2): consistent for elliptical distributions, including fat-tailed ones."""
    tau = stats.kendalltau(as_array(x), as_array(y)).statistic
    return float(math.sin(math.pi * tau / 2))


def check(x, y, alpha: float = ALPHA) -> list[Flag]:
    a, b = as_array(x, min_size=10), as_array(y, min_size=10)
    flags = [normality_flag(CHAPTER, a, alpha), normality_flag(CHAPTER, b, alpha)]
    # rank correlations: their p-values do not depend on the returns being normal
    moves = stats.spearmanr(a, b)
    sizes = stats.spearmanr(np.abs(a - np.median(a)), np.abs(b - np.median(b)))
    hidden = sizes.pvalue < alpha and moves.pvalue >= alpha
    flags.append(Flag(CHAPTER, "correlation captures the dependence", "rank correlation of move sizes",
                      float(sizes.statistic), float(sizes.pvalue), bool(hidden),
                      f"moves correlate {moves.statistic:+.2f} but their sizes {sizes.statistic:+.2f}"
                      if hidden else ""))
    return flags


def beat_baseline(seed=0, runs: int = 400, n: int = 250, rho: float = 0.5) -> list[BaselineResult]:
    """Estimate a true correlation of 0.5 from one year of daily Student t(3) returns."""
    rng = rng_from(seed)
    corr = np.array([[1.0, rho], [rho, 1.0]])
    e_rob, e_pear = [], []
    for _ in range(runs):
        xy = correlated(n, [0.01, 0.01], corr, df=3, seed=rng)
        e_rob.append((robust_correlation(xy[:, 0], xy[:, 1]) - rho) ** 2)
        e_pear.append((pearson(xy[:, 0], xy[:, 1]) - rho) ** 2)
    a, b = np.array(e_rob), np.array(e_pear)
    return [BaselineResult(CHAPTER, "Kendall-based correlation", BASELINE,
                           "mean squared error of the estimated correlation", float(a.mean()), float(b.mean()),
                           wins=float(np.mean(a < b)), note=f"{runs} samples of {n} days, t(3) shocks, true 0.5")]
