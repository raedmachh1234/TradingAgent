"""Chapter 2, present value: money now against money later at a known interest rate.

Assumption: a known, constant rate and certain cash flows. Nothing statistical to test, so the check
never flags; the rate itself is an input the caller must justify.
Baseline beaten: comparing cash-flow streams by their plain sum, ignoring when the money arrives.
"""
from __future__ import annotations

import numpy as np

from .core import BaselineResult, Flag, rng_from

CHAPTER = 2
TITLE = "Present value"
ASSUMPTION = "none statistical: a known constant rate"
BASELINE = "undiscounted sum of cash flows"


def future_value(pv: float, rate: float, years: float) -> float:
    if rate <= -1:
        raise ValueError("rate must be above -100%")
    return pv * (1.0 + rate) ** years


def present_value(fv: float, rate: float, years: float) -> float:
    if rate <= -1:
        raise ValueError("rate must be above -100%")
    return fv / (1.0 + rate) ** years


def npv(cashflows, rate: float, times=None) -> float:
    """Present value of cash flows paid at ``times`` (in years; default 0, 1, 2, ...)."""
    cf = np.asarray(cashflows, dtype=float)
    t = np.arange(cf.size, dtype=float) if times is None else np.asarray(times, dtype=float)
    return float(np.sum(cf / (1.0 + rate) ** t))


def terminal_wealth(cashflows, rate: float, horizon: float, times=None) -> float:
    """Wealth at ``horizon`` when every cash flow is reinvested at ``rate`` until then."""
    cf = np.asarray(cashflows, dtype=float)
    t = np.arange(cf.size, dtype=float) if times is None else np.asarray(times, dtype=float)
    return float(np.sum(cf * (1.0 + rate) ** (horizon - t)))


def check() -> list[Flag]:
    return []


def beat_baseline(seed=0, pairs: int = 2000) -> list[BaselineResult]:
    """Choose between an early and a late payment by NPV or by the plain sum, then measure the wealth
    each choice gives at a common horizon when reinvested at the same rate (regret against the best)."""
    rng = rng_from(seed)
    regret_m, regret_b = [], []
    for _ in range(pairs):
        rate = rng.uniform(0.0, 0.12)
        early_t, late_t = rng.uniform(0, 3), rng.uniform(3, 10)
        early = rng.uniform(50, 150)
        late = early * rng.uniform(0.9, 2.0)
        horizon = 10.0
        w_early = terminal_wealth([early], rate, horizon, [early_t])
        w_late = terminal_wealth([late], rate, horizon, [late_t])
        best = max(w_early, w_late)
        pick_m = w_early if npv([early], rate, [early_t]) >= npv([late], rate, [late_t]) else w_late
        pick_b = w_early if early >= late else w_late
        regret_m.append(best - pick_m)
        regret_b.append(best - pick_b)
    rm, rb = np.array(regret_m), np.array(regret_b)
    return [BaselineResult(CHAPTER, "choose by NPV", BASELINE,
                           "average wealth lost at year 10 against the better choice", float(rm.mean()),
                           float(rb.mean()), wins=float(np.mean(rm <= rb)),
                           note=f"{pairs} random early-versus-late payment choices")]
