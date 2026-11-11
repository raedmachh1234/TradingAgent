"""Chapter 3, expected value: the average result of a bet over many repetitions.

Assumption: the probabilities are known and the plays are independent. With real trades both are estimated,
so the check asks whether the measured edge is distinguishable from zero and whether results are independent.
Baseline beaten: picking the bet that wins most often, which ignores how much each outcome pays.
"""
from __future__ import annotations

import math

import numpy as np
from scipy import stats

from .core import ALPHA, BaselineResult, Flag, as_array, independence_flag, rng_from

CHAPTER = 3
TITLE = "Expected value"
ASSUMPTION = "known probabilities, independent plays"
BASELINE = "pick the bet with the highest win rate"


def expected_value(payoffs, probs) -> float:
    x = np.asarray(payoffs, dtype=float)
    p = np.asarray(probs, dtype=float)
    if x.shape != p.shape:
        raise ValueError("payoffs and probabilities must have the same length")
    if (p < 0).any() or abs(p.sum() - 1.0) > 1e-9:
        raise ValueError("probabilities must be non-negative and sum to 1")
    return float(x @ p)


def bet_ev(p_win: float, win: float, lose: float = 1.0) -> float:
    """Expected profit of a bet that pays ``win`` with probability ``p_win`` and costs ``lose`` otherwise."""
    if not 0 <= p_win <= 1:
        raise ValueError("p_win must be a probability")
    return p_win * win - (1.0 - p_win) * lose


def edge_interval(outcomes, alpha: float = ALPHA) -> tuple[float, float, float]:
    """Mean result per play with a two-sided (1 - alpha) confidence interval: (mean, low, high)."""
    x = as_array(outcomes, min_size=2)
    se = x.std(ddof=1) / math.sqrt(x.size)
    z = stats.norm.ppf(1 - alpha / 2)
    return float(x.mean()), float(x.mean() - z * se), float(x.mean() + z * se)


def check(outcomes, alpha: float = ALPHA) -> list[Flag]:
    """Is the measured edge real, and are the results of successive plays independent?"""
    mean, low, high = edge_interval(outcomes, alpha)
    unclear = low <= 0 <= high
    flags = [Flag(CHAPTER, "edge is known", f"{100 * (1 - alpha):.0f}% interval for the mean", mean, None,
                  unclear, f"interval [{low:.4g}, {high:.4g}] contains zero" if unclear else
                  f"interval [{low:.4g}, {high:.4g}]")]
    x = as_array(outcomes)
    if x.size >= 30:
        flags.append(independence_flag(CHAPTER, x, lags=min(10, x.size // 5), alpha=alpha))
    return flags


def beat_baseline(seed=0, pairs: int = 5000) -> list[BaselineResult]:
    """Random pairs of bets: choose by expected value or by win rate, score by the chosen bet's true EV."""
    rng = rng_from(seed)
    p = rng.uniform(0.05, 0.95, (pairs, 2))
    win = rng.uniform(0.2, 5.0, (pairs, 2))
    lose = rng.uniform(0.2, 5.0, (pairs, 2))
    ev = p * win - (1 - p) * lose
    rows = np.arange(pairs)
    by_ev = ev[rows, ev.argmax(axis=1)]
    by_rate = ev[rows, p.argmax(axis=1)]
    return [BaselineResult(CHAPTER, "choose by expected value", BASELINE,
                           "average expected profit per play of the chosen bet", float(by_ev.mean()),
                           float(by_rate.mean()), lower_is_better=False,
                           wins=float(np.mean(by_ev >= by_rate)), note=f"{pairs} random pairs of bets")]
