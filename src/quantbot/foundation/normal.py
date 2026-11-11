"""Chapter 6, the bell curve: probabilities of returns under the normal distribution.

Assumption: returns are normal. The check is Jarque-Bera on skewness and kurtosis; when it fails, normal
tail probabilities are too small (see chapter 16).
Baseline beaten: counting how often a loss happened in a short history. When returns really are normal,
the fitted bell curve estimates a tail probability far more precisely than the raw count.
"""
from __future__ import annotations

from statistics import NormalDist

import numpy as np

from .core import ALPHA, BaselineResult, Flag, as_array, normality_flag, rng_from

CHAPTER = 6
TITLE = "Bell curve"
ASSUMPTION = "normal returns"
BASELINE = "count past losses in a short history"


def prob_below(x: float, mu: float, sigma: float) -> float:
    if sigma <= 0:
        raise ValueError("sigma must be positive")
    return NormalDist(mu, sigma).cdf(x)


def return_period(prob: float) -> float:
    """'One period in N': how many periods pass on average between events of probability ``prob``."""
    if not 0 < prob <= 1:
        raise ValueError("prob must be in (0, 1]")
    return 1.0 / prob


def fitted_prob_below(returns, x: float) -> float:
    r = as_array(returns)
    return prob_below(x, float(r.mean()), float(r.std(ddof=1)))


def check(returns, alpha: float = ALPHA) -> list[Flag]:
    return [normality_flag(CHAPTER, returns, alpha)]


def beat_baseline(seed=0, runs: int = 4000, n: int = 60) -> list[BaselineResult]:
    """Estimate P(return < mean - 2 sd) from 60 normal observations: fitted normal vs raw frequency."""
    rng = rng_from(seed)
    mu, sigma = 0.008, 0.045
    x = mu - 2 * sigma
    truth = prob_below(x, mu, sigma)
    data = mu + sigma * rng.standard_normal((runs, n))
    m, s = data.mean(axis=1), data.std(axis=1, ddof=1)
    fitted = np.array([NormalDist(a, b).cdf(x) for a, b in zip(m, s, strict=True)])
    counted = (data < x).mean(axis=1)
    err_f, err_c = (fitted - truth) ** 2, (counted - truth) ** 2
    return [BaselineResult(CHAPTER, "fit a normal distribution", BASELINE,
                           "root mean squared error of P(loss beyond 2 sd)", float(np.sqrt(err_f.mean())),
                           float(np.sqrt(err_c.mean())), wins=float(np.mean(err_f < err_c)),
                           note=f"{runs} histories of {n} normal monthly returns; true probability {truth:.4f}")]
