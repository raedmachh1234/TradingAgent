"""Chapter 15, Monte Carlo: simulate many futures and read risks and averages from them.

Assumption: the simulated shocks have the distribution the model gives them, usually independent normal
draws. If the history used to calibrate the model shows fat tails or volatility clustering, normal draws
understate the bad paths; the check flags that and ``block_bootstrap`` resamples real blocks instead.
Baseline beaten: plain Monte Carlo against antithetic variates, by the standard error of the estimate for the
same number of random draws.
"""
from __future__ import annotations

import numpy as np

from .core import ALPHA, BaselineResult, Flag, as_array, clustering_flag, normality_flag, rng_from
from .drag import growth_rate

CHAPTER = 15
TITLE = "Monte Carlo"
ASSUMPTION = "simulated shocks match reality (normal, independent)"
BASELINE = "plain Monte Carlo"


def paths_needed(se_now: float, se_target: float, n_now: int) -> float:
    """Paths needed to reach ``se_target``: the standard error falls with the square root of the paths."""
    if se_target <= 0 or se_now <= 0:
        raise ValueError("standard errors must be positive")
    return n_now * (se_now / se_target) ** 2


def median_growth(mu: float, sigma: float) -> float:
    """The median growth rate of simulated wealth paths (chapter 9's mu - sigma^2 / 2)."""
    return growth_rate(mu, sigma)


def terminal_wealth(m: float, s: float, years: int, paths: int, seed=None, start: float = 1.0,
                    antithetic: bool = False) -> np.ndarray:
    """Wealth after ``years`` of normal yearly log returns with mean m and sd s."""
    rng = rng_from(seed)
    if antithetic:
        half = rng.standard_normal(((paths + 1) // 2, years))
        z = np.vstack([half, -half])[:paths]
    else:
        z = rng.standard_normal((paths, years))
    return start * np.exp((m + s * z).sum(axis=1))


def mean_with_se(samples) -> tuple[float, float]:
    x = as_array(samples, min_size=2)
    return float(x.mean()), float(x.std(ddof=1) / np.sqrt(x.size))


def block_bootstrap(returns, length: int, block: int = 20, seed=None) -> np.ndarray:
    """Resample ``length`` returns as consecutive blocks of the history, keeping clusters and fat tails."""
    x = as_array(returns, min_size=block + 1)
    rng = rng_from(seed)
    starts = rng.integers(0, x.size - block + 1, -(-length // block))
    return np.concatenate([x[s:s + block] for s in starts])[:length]


def check(calibration_returns, alpha: float = ALPHA) -> list[Flag]:
    return [normality_flag(CHAPTER, calibration_returns, alpha),
            clustering_flag(CHAPTER, calibration_returns, alpha=alpha)]


def beat_baseline(seed=0, reps: int = 300, paths: int = 2000) -> list[BaselineResult]:
    """Estimate expected wealth after 30 years (log returns 6% +/- 20% a year), repeated many times:
    the spread of the estimates is its true standard error."""
    rng = rng_from(seed)
    plain = [terminal_wealth(0.06, 0.2, 30, paths, seed=rng).mean() for _ in range(reps)]
    anti = [terminal_wealth(0.06, 0.2, 30, paths, seed=rng, antithetic=True).mean() for _ in range(reps)]
    a, b = float(np.std(anti, ddof=1)), float(np.std(plain, ddof=1))
    return [BaselineResult(CHAPTER, "antithetic variates", BASELINE,
                           "standard error of the expected-wealth estimate", a, b,
                           note=f"{reps} repetitions of {paths} paths each; true value "
                                f"{np.exp(30 * (0.06 + 0.02)):.2f}")]
