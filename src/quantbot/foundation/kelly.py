"""Chapter 14, the Kelly criterion: the bet size that maximises long-run growth.

Assumptions: the win probability and payoff are known, and bets are independent. With a real track record
the probability is estimated, and betting full Kelly on an estimate overbets on average because growth falls
faster above the optimum than below it. The check flags an edge that is not distinguishable from zero and
results that are not independent (runs test). ``shrunk_kelly`` scales the bet down by the estimation noise.
Baseline beaten: full Kelly on the estimated win rate.
"""
from __future__ import annotations

import math

import numpy as np
from scipy import stats

from .core import ALPHA, BaselineResult, Flag, rng_from, runs_test

CHAPTER = 14
TITLE = "Kelly criterion"
ASSUMPTION = "known edge, independent bets"
BASELINE = "full Kelly on the estimated win rate"


def kelly_fraction(p: float, b: float) -> float:
    """Fraction of capital to bet when a bet wins b per 1 staked with probability p (and loses the stake)."""
    if b <= 0 or not 0 <= p <= 1:
        raise ValueError("need b > 0 and 0 <= p <= 1")
    return p - (1 - p) / b


def log_growth(f: float, p: float, b: float) -> float:
    """Expected log growth per bet when betting fraction f."""
    if not 0 <= f < 1:
        raise ValueError("f must be in [0, 1)")
    return p * math.log1p(b * f) + (1 - p) * math.log1p(-f)


def shrunk_kelly(wins: int, n: int, b: float) -> float:
    """Kelly on an estimated win rate, scaled by f^2 / (f^2 + var(f)) to allow for estimation noise."""
    if n < 1 or not 0 <= wins <= n:
        raise ValueError("need 0 <= wins <= n and n >= 1")
    p = wins / n
    f = kelly_fraction(p, b)
    if f <= 0:
        return 0.0
    var_f = (1 + 1 / b) ** 2 * p * (1 - p) / n
    return min(f * f * f / (f * f + var_f), 0.99)


def check(outcomes, b: float, alpha: float = ALPHA) -> list[Flag]:
    """``outcomes``: 1 for a winning bet, 0 for a losing one."""
    o = np.asarray(outcomes).astype(bool).ravel()
    n = o.size
    if n < 10:
        raise ValueError("need at least 10 bets")
    p = o.mean()
    f = kelly_fraction(p, b)
    se_f = (1 + 1 / b) * math.sqrt(max(p * (1 - p), 1e-12) / n)
    low = f - stats.norm.ppf(1 - alpha) * se_f
    z, p_runs = runs_test(o)
    return [
        Flag(CHAPTER, "edge is known", "one-sided lower bound of the Kelly fraction", low, None, low <= 0,
             f"estimated fraction {f:.3f}, lower bound {low:.3f} from {n} bets"),
        Flag(CHAPTER, "independent bets", "runs test", z, p_runs, p_runs < alpha,
             "wins and losses come in streaks" if (p_runs < alpha and z < 0) else
             "wins and losses alternate too often" if p_runs < alpha else ""),
    ]


def beat_baseline(seed=0, draws: int = 20000, n: int = 50, p: float = 0.55, b: float = 1.0) -> list[BaselineResult]:
    """A real edge (p 0.55, even money, Kelly 10%) measured from 50 past bets. Score each sizing rule by the
    true expected log growth of the bet it chooses, averaged over many possible track records."""
    rng = rng_from(seed)
    wins = rng.binomial(n, p, draws)
    full = np.clip([kelly_fraction(w / n, b) for w in wins], 0.0, 0.99)
    shrunk = np.array([shrunk_kelly(int(w), n, b) for w in wins])
    g_full = np.array([log_growth(f, p, b) for f in full])
    g_shrunk = np.array([log_growth(f, p, b) for f in shrunk])
    best = log_growth(kelly_fraction(p, b), p, b)
    return [BaselineResult(CHAPTER, "Kelly shrunk for estimation noise", BASELINE,
                           "true expected log growth per bet (x 1000)", float(g_shrunk.mean() * 1000),
                           float(g_full.mean() * 1000), lower_is_better=False,
                           wins=float(np.mean(g_shrunk >= g_full)),
                           note=f"{draws} track records of {n} bets; growth with the true edge known "
                                f"{best * 1000:.2f}; not betting scores 0, so 50 bets are too few to size "
                                f"from")]
