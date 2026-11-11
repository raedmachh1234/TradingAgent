"""Chapter 16, fat tails: big moves happen far more often than the bell curve allows.

Assumption tested: normal tails. The check counts moves beyond k standard deviations against the number a
normal distribution predicts (a binomial test), alongside Jarque-Bera; ``hill_tail_index`` measures how fat
the tail is and ``fit_student_t`` gives a usable tail model.
Baseline beaten: the normal distribution's tail probability, on fat-tailed data.
"""
from __future__ import annotations

import math

import numpy as np
from scipy import stats

from .core import ALPHA, BaselineResult, Flag, as_array, normality_flag, rng_from
from .synthetic import student_t

CHAPTER = 16
TITLE = "Fat tails"
ASSUMPTION = "normal tails"
BASELINE = "normal tail probability"


def prob_below_sigma(k: float) -> float:
    """P(Z < -k) for a standard normal Z."""
    return 0.5 * math.erfc(k / math.sqrt(2))


def years_between(prob: float, periods_per_year: int = 252) -> float:
    if prob <= 0:
        raise ValueError("prob must be positive")
    return 1.0 / (prob * periods_per_year)


def excess_kurtosis(returns) -> float:
    return float(stats.kurtosis(as_array(returns, min_size=4)))


def k_sigma_moves(returns, k: float = 4.0) -> tuple[int, float]:
    """(observed count, count a normal distribution predicts) of moves beyond k sd, in either direction."""
    x = as_array(returns)
    z = (x - x.mean()) / x.std(ddof=1)
    return int(np.sum(np.abs(z) > k)), float(x.size * 2 * prob_below_sigma(k))


def hill_tail_index(returns, tail: float = 0.05) -> float:
    """Hill estimator of the left-tail index alpha from the largest ``tail`` share of losses; normal-like
    tails give large values, alpha below about 4 means the fourth moment (kurtosis) is unreliable."""
    losses = np.sort(-as_array(returns, min_size=40))[::-1]
    k = max(int(tail * losses.size), 10)
    top, threshold = losses[:k], losses[k]
    if threshold <= 0:
        raise ValueError("too few losses for the Hill estimator")
    return float(1.0 / np.mean(np.log(top / threshold)))


def fit_student_t(returns) -> tuple[float, float, float]:
    """Maximum-likelihood Student t fit: (degrees of freedom, location, scale)."""
    df, loc, scale = stats.t.fit(as_array(returns, min_size=30))
    return float(df), float(loc), float(scale)


def tail_prob_student_t(x: float, df: float, loc: float, scale: float) -> float:
    return float(stats.t.cdf((x - loc) / scale, df))


def check(returns, alpha: float = ALPHA, k: float = 4.0) -> list[Flag]:
    x = as_array(returns, min_size=50)
    observed, expected = k_sigma_moves(x, k)
    p = float(stats.binom.sf(observed - 1, x.size, 2 * prob_below_sigma(k))) if observed > 0 else 1.0
    return [normality_flag(CHAPTER, x, alpha),
            Flag(CHAPTER, "normal tails", f"moves beyond {k:g} sd against the normal count", float(observed),
                 p, p < alpha, f"{observed} moves where a normal market has {expected:.2f}")]


def beat_baseline(seed=0, runs: int = 30, n: int = 2500, df: float = 4.0, k: float = 4.0) -> list[BaselineResult]:
    """Ten years of daily t(4) returns: estimate P(return < -4 sd), score by the error in log probability."""
    rng = rng_from(seed)
    sd_scale = math.sqrt((df - 2) / df)
    truth = float(stats.t.cdf(-k / sd_scale, df))
    e_t, e_n = [], []
    for _ in range(runs):
        x = student_t(n, df, 1.0, seed=rng)  # true mean 0 and sd 1, so the event is x < -k
        m, s = x.mean(), x.std(ddof=1)
        fdf, loc, scale = fit_student_t(x)
        p_t = tail_prob_student_t(-k, fdf, loc, scale)
        p_n = float(stats.norm.cdf(-k, m, s))
        e_t.append(abs(math.log(p_t / truth)))
        e_n.append(abs(math.log(p_n / truth)))
    a, b = np.array(e_t), np.array(e_n)
    return [BaselineResult(CHAPTER, "Student t fit", BASELINE, "absolute error of log P(loss beyond 4 sd)",
                           float(a.mean()), float(b.mean()), wins=float(np.mean(a < b)),
                           note=f"{runs} samples of {n} days from t({df:g}); true probability {truth:.2e}, "
                                f"normal says {prob_below_sigma(k):.2e}")]
