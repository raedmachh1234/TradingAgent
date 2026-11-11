"""The book foundation: one module per chapter of "Quantitative Finance From Scratch".

Each chapter module states its ASSUMPTION, offers ``check(...)`` that flags data breaking it, and
``beat_baseline(seed)`` that measures the chapter's method against the naive BASELINE on synthetic data with
a known truth. ``fixtures.reproduce()`` re-computes the book's 57 worked answers through these modules.
"""
from __future__ import annotations

from . import (capm, correlation, diversification, drag, expectation, kelly, minvariance, montecarlo, normal,
               randomwalk, returns, scaling, sharpe, tails, timevalue, var, volatility)

CHAPTERS = {
    1: returns, 2: timevalue, 3: expectation, 4: randomwalk, 5: scaling, 6: normal, 7: volatility,
    8: sharpe, 9: drag, 10: correlation, 11: diversification, 12: minvariance, 13: capm, 14: kelly,
    15: montecarlo, 16: tails, 17: var,
}
