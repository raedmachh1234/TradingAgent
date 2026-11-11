"""Chapter 9, volatility drag: why a +50% then -50% sequence loses money, and g = mu - sigma^2 / 2.

Assumption: the shortcut g = mu - sigma^2 / 2 is a second-order approximation that is exact for normal log
returns. With skewed or fat-tailed returns the true drag is larger; the check runs Jarque-Bera and reports
the gap between the measured compound growth and the shortcut.
Baseline beaten: using the average return mu itself as the growth rate of a compounding investment.
"""
from __future__ import annotations

import numpy as np

from .core import ALPHA, BaselineResult, Flag, as_array, normality_flag, rng_from

CHAPTER = 9
TITLE = "Volatility drag"
ASSUMPTION = "normal returns (second-order approximation)"
BASELINE = "average return as the growth rate"


def two_period_return(r1: float, r2: float) -> float:
    return (1 + r1) * (1 + r2) - 1


def growth_rate(mu: float, sigma: float) -> float:
    """Median compound growth rate per period for average return ``mu`` and volatility ``sigma``."""
    return mu - sigma**2 / 2


def realized_growth(returns) -> float:
    """Compound growth per period actually achieved: exp(mean(log(1 + r))) - 1."""
    r = as_array(returns, min_size=1)
    if (r <= -1).any():
        raise ValueError("a return of -100% or below ends the compounding")
    return float(np.expm1(np.mean(np.log1p(r))))


def check(returns, alpha: float = ALPHA) -> list[Flag]:
    r = as_array(returns)
    flag = normality_flag(CHAPTER, r, alpha)
    gap = realized_growth(r) - growth_rate(float(r.mean()), float(r.std(ddof=0)))
    detail = f"{flag.detail}; measured growth minus shortcut {gap:+.2e} per period"
    return [Flag(flag.chapter, flag.assumption, flag.test, flag.statistic, flag.p_value, flag.failed, detail)]


def beat_baseline(seed=0, paths: int = 20000, years: int = 30) -> list[BaselineResult]:
    """Thirty years of yearly returns with mean 8% and volatility 20%: predict the median compound growth."""
    rng = rng_from(seed)
    mu, sigma = 0.08, 0.20
    s2 = np.log(1 + sigma**2 / (1 + mu) ** 2)  # lognormal yearly returns with exactly this mean and sd
    m = np.log(1 + mu) - s2 / 2
    log_r = m + np.sqrt(s2) * rng.standard_normal((paths, years))
    growth = np.expm1(log_r.mean(axis=1))
    realized_median = float(np.median(growth))
    err_m = abs(growth_rate(mu, sigma) - realized_median)
    err_b = abs(mu - realized_median)
    return [BaselineResult(CHAPTER, "g = mu - sigma^2 / 2", BASELINE,
                           "absolute error of the predicted median yearly growth", err_m, err_b,
                           note=f"{paths} simulated 30-year paths; realized median growth {realized_median:.4f}")]
