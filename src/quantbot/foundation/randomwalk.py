"""Chapter 4, the random walk: prices built from independent up and down steps.

Assumption: each step is independent of the ones before. The check separates direction from size: a
robust Box-Pierce test and the robust variance ratio ask whether past moves predict the next move, and the
McLeod-Li test asks whether big moves follow big moves (volatility clustering).
Baseline beaten: forecasting a reversal back to the recent average (the gambler's fallacy) or a
continuation of the last move; on a random walk the last price is the best forecast.
"""
from __future__ import annotations

import math

import numpy as np

from .core import (ALPHA, BaselineResult, Flag, as_array, independence_flag, mcleod_li, rng_from,
                   variance_ratio)

CHAPTER = 4
TITLE = "Random walk"
ASSUMPTION = "independent steps"
BASELINE = "forecast a move back to the 20-step average"


def end_distribution(n_steps: int, step: float = 1.0) -> dict[float, float]:
    """Exact distribution of the net move after ``n_steps`` fair +step/-step moves: {move: probability}."""
    if n_steps < 0:
        raise ValueError("n_steps must be non-negative")
    return {step * (2 * k - n_steps): math.comb(n_steps, k) / 2**n_steps for k in range(n_steps + 1)}


def prob_net_move(n_steps: int, move: float = 0.0, step: float = 1.0) -> float:
    return end_distribution(n_steps, step).get(move, 0.0)


def n_end_values(n_steps: int) -> int:
    return len(end_distribution(n_steps))


def arcsine_share(fraction: float) -> float:
    """Share of long fair walks that spend more than ``fraction`` of the time on one side of the start
    (arcsine law). Needs 0.5 <= fraction <= 1."""
    if not 0.5 <= fraction <= 1:
        raise ValueError("fraction must be between 0.5 and 1")
    return 2.0 * (2.0 / math.pi) * math.asin(math.sqrt(1.0 - fraction))


def simulate(n_steps: int, seed=None, step: float = 1.0, start: float = 0.0) -> np.ndarray:
    steps = np.where(rng_from(seed).random(n_steps) < 0.5, -step, step)
    return start + np.cumsum(steps)


def check(returns, alpha: float = ALPHA, lags: int = 10, q: int = 5) -> list[Flag]:
    """Direction: are moves predictable from past moves? Size: do big moves follow big moves?"""
    x = as_array(returns, min_size=max(lags, q) + 20)
    vr, z, p = variance_ratio(x, q)
    detail = ("momentum: moves continue" if vr > 1 else "mean reversion: moves reverse") if p < alpha else ""
    q_size, p_size = mcleod_li(x, lags)
    return [independence_flag(CHAPTER, x, lags, alpha),
            Flag(CHAPTER, "uncorrelated returns", f"variance ratio, {q} periods", vr, p, p < alpha, detail),
            Flag(CHAPTER, "independent step sizes", f"McLeod-Li, {lags} lags", q_size, p_size, p_size < alpha,
                 "big moves follow big moves" if p_size < alpha else "")]


def beat_baseline(seed=0, walks: int = 200, steps: int = 2000, window: int = 20) -> list[BaselineResult]:
    """One-step forecasts of random-walk prices: last price vs reversal to the average vs trend."""
    rng = rng_from(seed)
    prices = 100.0 + np.cumsum(rng.standard_normal((walks, steps)), axis=1)
    kernel = np.ones(window) / window
    mse_rw, mse_mr, mse_tr = [], [], []
    for p in prices:
        avg = np.convolve(p, kernel, mode="valid")  # avg[i] = mean of p[i : i + window]
        last = p[window - 1:-1]
        target = p[window:]
        reversal = avg[:-1]
        trend = last + (p[window - 1:-1] - p[window - 2:-2])
        mse_rw.append(np.mean((target - last) ** 2))
        mse_mr.append(np.mean((target - reversal) ** 2))
        mse_tr.append(np.mean((target - trend) ** 2))
    rw, mr, tr = map(np.array, (mse_rw, mse_mr, mse_tr))
    return [BaselineResult(CHAPTER, "forecast the last price", BASELINE, "mean squared forecast error",
                           float(rw.mean()), float(mr.mean()), wins=float(np.mean(rw < mr)),
                           note=f"{walks} random walks of {steps} steps; trend-following forecast scored "
                                f"{tr.mean():.2f}")]
