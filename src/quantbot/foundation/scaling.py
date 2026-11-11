"""Chapter 5, the square-root rule: risk over n periods is sqrt(n) times the risk of one period.

Assumption: uncorrelated returns. Volatility clustering does not break the rule for the average risk, but
autocorrelation does: momentum makes long-horizon risk larger than sqrt(n) predicts, mean reversion smaller.
The check uses the robust variance ratio; ``scale_vol_adjusted`` corrects the rule with measured
autocorrelations.
Baseline beaten: scaling risk linearly with time (n times the one-period risk).
"""
from __future__ import annotations

import math

import numpy as np

from .core import ALPHA, BaselineResult, Flag, as_array, autocorrelations, rng_from, variance_ratio
from .synthetic import ar1

CHAPTER = 5
TITLE = "Square-root rule"
ASSUMPTION = "uncorrelated returns"
BASELINE = "scale risk linearly with time"


def scale_vol(vol: float, periods: float) -> float:
    if periods < 0:
        raise ValueError("periods must be non-negative")
    return vol * math.sqrt(periods)


def scale_vol_linear(vol: float, periods: float) -> float:
    """The common mistake: n periods are taken as n times as risky."""
    return vol * periods


def variance_ratio_from(rho, periods: int) -> float:
    """Variance of an n-period sum relative to n times the one-period variance, from autocorrelations
    rho[0] = lag 1, rho[1] = lag 2, ... (lags beyond those given count as zero)."""
    rho = np.asarray(rho, dtype=float)
    k = np.arange(1, min(periods, rho.size + 1))
    return 1.0 + 2.0 * float(np.sum((1.0 - k / periods) * rho[: k.size]))


def scale_vol_adjusted(returns, periods: int, max_lag: int = 10) -> float:
    """sqrt rule corrected for autocorrelation up to ``max_lag``: sd * sqrt(n * VR(n))."""
    x = as_array(returns, min_size=max_lag + 20)
    rho = autocorrelations(x, min(max_lag, periods - 1)) if periods > 1 else np.zeros(0)
    vr = max(variance_ratio_from(rho, periods), 0.0)
    return float(x.std(ddof=1) * math.sqrt(periods * vr))


def check(returns, alpha: float = ALPHA, q: int = 10) -> list[Flag]:
    x = as_array(returns, min_size=q + 20)
    vr, z, p = variance_ratio(x, q)
    off = abs(math.sqrt(vr) - 1)
    detail = f"sqrt rule {'under' if vr > 1 else 'over'}states {q}-period risk by about {100 * off:.0f}%" \
        if p < alpha else ""
    return [Flag(CHAPTER, "uncorrelated returns", f"variance ratio, {q} periods", vr, p, p < alpha, detail)]


def _realized_block_vol(x: np.ndarray, n: int) -> float:
    m = (x.size // n) * n
    return float(x[:m].reshape(-1, n).sum(axis=1).std(ddof=1))


def beat_baseline(seed=0, seeds: int = 40, days: int = 20000, horizon: int = 10) -> list[BaselineResult]:
    """Predict the risk of 10-day returns from daily data: sqrt rule vs linear rule on independent returns,
    and the autocorrelation-adjusted rule vs the plain sqrt rule on momentum returns (phi = 0.2)."""
    rng = rng_from(seed)
    e_sqrt, e_lin, e_adj, e_plain = [], [], [], []
    for _ in range(seeds):
        iid = 0.01 * rng.standard_normal(days)
        realized = _realized_block_vol(iid, horizon)
        sd = iid.std(ddof=1)
        e_sqrt.append(abs(scale_vol(sd, horizon) - realized))
        e_lin.append(abs(scale_vol_linear(sd, horizon) - realized))
        mom = ar1(days, 0.2, 0.01, seed=rng)
        realized = _realized_block_vol(mom, horizon)
        e_adj.append(abs(scale_vol_adjusted(mom, horizon) - realized))
        e_plain.append(abs(scale_vol(mom.std(ddof=1), horizon) - realized))
    a, b, c, d = map(np.array, (e_sqrt, e_lin, e_adj, e_plain))
    return [
        BaselineResult(CHAPTER, "sqrt rule", BASELINE, "absolute error of the predicted 10-day sd",
                       float(a.mean()), float(b.mean()), wins=float(np.mean(a < b)),
                       note=f"independent daily returns, {seeds} runs of {days} days"),
        BaselineResult(CHAPTER, "sqrt rule adjusted for autocorrelation", "plain sqrt rule",
                       "absolute error of the predicted 10-day sd", float(c.mean()), float(d.mean()),
                       wins=float(np.mean(c < d)), note=f"momentum returns (phi 0.2), {seeds} runs"),
    ]
