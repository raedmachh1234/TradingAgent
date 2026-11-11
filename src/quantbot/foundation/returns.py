"""Chapter 1, returns: simple and log returns, and how they add up over time.

Assumption: none statistical. These are exact identities, so the check never flags.
Baseline beaten: adding simple returns together, which misses compounding.
"""
from __future__ import annotations

import math

import numpy as np

from .core import BaselineResult, Flag, as_array, rng_from

CHAPTER = 1
TITLE = "Returns"
ASSUMPTION = "none: exact arithmetic"
BASELINE = "sum of simple returns"


def simple_return(p0: float, p1: float) -> float:
    if p0 <= 0:
        raise ValueError("starting price must be positive")
    return p1 / p0 - 1.0


def log_return(p0: float, p1: float) -> float:
    if p0 <= 0 or p1 <= 0:
        raise ValueError("prices must be positive")
    return math.log(p1 / p0)


def recovery_return(loss: float) -> float:
    """Return needed to get back to the start after a return of ``loss`` (for example -25% needs +33.3%)."""
    if loss <= -1:
        raise ValueError("a loss of 100% or more cannot be recovered")
    return 1.0 / (1.0 + loss) - 1.0


def compound(returns) -> float:
    """Total return of a sequence of simple returns: (1 + r1)(1 + r2)... - 1."""
    r = np.asarray(returns, dtype=float)
    if (r <= -1).any():
        raise ValueError("a simple return of -100% or below wipes out the position")
    return float(np.expm1(np.sum(np.log1p(r))))


def sum_log_returns(returns) -> float:
    """Log returns add over time: the sum of log(1 + r) for a sequence of simple returns."""
    r = np.asarray(returns, dtype=float)
    return float(np.sum(np.log1p(r)))


def check(returns) -> list[Flag]:
    as_array(returns, min_size=1)
    return []


def beat_baseline(seed=0, paths: int = 1000, days: int = 252) -> list[BaselineResult]:
    """Total return of random one-year price paths: compounding vs adding the daily simple returns."""
    rng = rng_from(seed)
    r = 0.0003 + 0.015 * rng.standard_normal((paths, days))
    prices = 100.0 * np.cumprod(1 + r, axis=1)
    truth = prices[:, -1] / 100.0 - 1
    method = np.expm1(np.sum(np.log1p(r), axis=1))
    naive = r.sum(axis=1)
    err_m, err_b = np.abs(method - truth), np.abs(naive - truth)
    return [BaselineResult(CHAPTER, "compound the returns", BASELINE,
                           "mean absolute error of the yearly return", float(err_m.mean()),
                           float(err_b.mean()), wins=float(np.mean(err_m < err_b)),
                           note=f"{paths} random one-year paths")]
