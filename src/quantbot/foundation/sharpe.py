"""Chapter 8, the Sharpe ratio: excess return per unit of risk.

Assumptions: annualising with sqrt(periods) needs independent returns, and the usual error bar needs normal
returns. The check flags both. ``annualize_sharpe_lo`` corrects for autocorrelation (Lo, 2002);
``sharpe_se`` and ``probabilistic_sharpe`` widen the error bar for skewness and fat tails (Mertens, 2002;
Bailey and Lopez de Prado, 2012).
Baseline beaten: sqrt(252) annualisation of a daily Sharpe ratio when returns are autocorrelated.
"""
from __future__ import annotations

import math

import numpy as np
from scipy import stats

from .core import (ALPHA, BaselineResult, Flag, as_array, autocorrelations, independence_flag,
                   normality_flag, rng_from)
from .synthetic import ar1

CHAPTER = 8
TITLE = "Sharpe ratio"
ASSUMPTION = "independent, normal returns"
BASELINE = "sqrt(252) annualisation"


def sharpe(mean_return: float, vol: float, rf: float = 0.0) -> float:
    if vol <= 0:
        raise ValueError("vol must be positive")
    return (mean_return - rf) / vol


def mix_with_cash(weight: float, mean_return: float, vol: float, rf: float) -> tuple[float, float]:
    """Expected return and volatility of ``weight`` in a risky fund and the rest in cash paying ``rf``."""
    return weight * mean_return + (1 - weight) * rf, abs(weight) * vol


def annualize_sharpe(sr: float, periods: int = 252) -> float:
    """sqrt-of-time annualisation; exact only for independent returns."""
    return sr * math.sqrt(periods)


def lo_factor(rho, periods: int) -> float:
    """eta(q) = q / sqrt(q + 2 sum_{k<q} (q - k) rho_k), Lo (2002); lags beyond those given count as zero."""
    rho = np.asarray(rho, dtype=float)
    k = np.arange(1, min(periods, rho.size + 1))
    denom = periods + 2.0 * float(np.sum((periods - k) * rho[: k.size]))
    if denom <= 0:
        raise ValueError("autocorrelations imply a non-positive variance")
    return periods / math.sqrt(denom)


def annualize_sharpe_lo(returns, periods: int = 252, rf: float = 0.0, max_lag: int = 10) -> float:
    x = as_array(returns, min_size=max_lag + 20) - rf
    sr = x.mean() / x.std(ddof=1)
    return float(sr * lo_factor(autocorrelations(x, max_lag), periods))


def sharpe_se(sr: float, n: int, skew: float = 0.0, excess_kurt: float = 0.0) -> float:
    """Standard error of a per-period Sharpe ratio estimated from n returns (Mertens, 2002)."""
    return math.sqrt(max(1 + sr * sr / 2 - skew * sr + excess_kurt / 4 * sr * sr, 1e-12) / n)


def probabilistic_sharpe(returns, benchmark: float = 0.0) -> float:
    """Probability that the true per-period Sharpe ratio exceeds ``benchmark`` (Bailey and Lopez de Prado)."""
    x = as_array(returns, min_size=10)
    sr = x.mean() / x.std(ddof=1)
    g3, g4 = float(stats.skew(x)), float(stats.kurtosis(x, fisher=False))
    denom = math.sqrt(max(1 - g3 * sr + (g4 - 1) / 4 * sr * sr, 1e-12))
    return float(stats.norm.cdf((sr - benchmark) * math.sqrt(x.size - 1) / denom))


def check(returns, alpha: float = ALPHA, lags: int = 10) -> list[Flag]:
    return [independence_flag(CHAPTER, returns, lags, alpha), normality_flag(CHAPTER, returns, alpha)]


def true_annual_sharpe_ar1(mu: float, sigma: float, phi: float, periods: int = 252) -> float:
    k = np.arange(1, periods)
    var = sigma**2 * (periods + 2.0 * float(np.sum((periods - k) * phi**k)))
    return periods * mu / math.sqrt(var)


def beat_baseline(seed=0, runs: int = 60, days: int = 25200, phi: float = 0.2) -> list[BaselineResult]:
    """Annual Sharpe ratio from 100 years of daily momentum returns: Lo's correction vs sqrt(252)."""
    rng = rng_from(seed)
    sigma = 0.01
    mu = 0.0004
    truth = true_annual_sharpe_ar1(mu, sigma, phi)
    e_lo, e_naive = [], []
    for _ in range(runs):
        x = ar1(days, phi, sigma, mu, seed=rng)
        e_lo.append(abs(annualize_sharpe_lo(x) - truth))
        e_naive.append(abs(annualize_sharpe(x.mean() / x.std(ddof=1)) - truth))
    a, b = np.array(e_lo), np.array(e_naive)
    return [BaselineResult(CHAPTER, "Lo's autocorrelation correction", BASELINE,
                           "absolute error of the annual Sharpe ratio", float(a.mean()), float(b.mean()),
                           wins=float(np.mean(a < b)),
                           note=f"momentum returns (phi {phi}), true annual Sharpe {truth:.2f}, {runs} runs")]
