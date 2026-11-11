"""The book's 57 worked answers, each re-computed through the chapter modules.

tests/fixtures/ebook_solutions.json holds the printed answer and its tolerance for every question (Phase 0);
this module maps each question to the library call that answers it.
"""
from __future__ import annotations

import json
import math
from collections.abc import Callable
from pathlib import Path

from . import (capm, correlation, diversification, drag, expectation, kelly, minvariance, montecarlo, normal,
               randomwalk, returns, scaling, sharpe, tails, timevalue, var, volatility)

FIXTURE_FILE = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "ebook_solutions.json"

_p5 = tails.prob_below_sigma(5)
_r7 = [1, -2, 3, 0, -2]

CALLS: dict[str, Callable[[], float]] = {
    "1.1a": lambda: returns.simple_return(80, 60),
    "1.1b": lambda: returns.recovery_return(-0.25),
    "1.2a": lambda: returns.compound([0.10, -0.10]),
    "1.2b": lambda: returns.sum_log_returns([0.10, -0.10]),
    "2.1": lambda: timevalue.future_value(1000, 0.04, 3),
    "2.2a": lambda: timevalue.present_value(500, 0.05, 2),
    "2.2b": lambda: timevalue.present_value(500, 0.08, 2),
    "2.fig": lambda: timevalue.future_value(100, 0.05, 10),
    "3.1": lambda: expectation.expected_value(range(1, 7), [1 / 6] * 6),
    "3.2a": lambda: expectation.bet_ev(1 / 37, 35, 1),
    "3.2b": lambda: expectation.bet_ev(18 / 37, 1, 1),
    "4.1a": lambda: randomwalk.prob_net_move(4, 0),
    "4.1b": lambda: randomwalk.n_end_values(4),
    "4.2": lambda: randomwalk.arcsine_share(0.9),
    "5.1a": lambda: scaling.scale_vol(0.01, 252),
    "5.1b": lambda: scaling.scale_vol(0.01, 4),
    "6.1": lambda: normal.prob_below(-0.24, 0.08, 0.16),
    "6.1b": lambda: normal.return_period(normal.prob_below(-0.24, 0.08, 0.16)),
    "7.1a": lambda: volatility.mean(_r7),
    "7.1b": lambda: volatility.volatility(_r7),
    "8.1a": lambda: sharpe.sharpe(0.09, 0.15, 0.03),
    "8.1b": lambda: sharpe.sharpe(0.06, 0.06, 0.03),
    "8.2a": lambda: sharpe.mix_with_cash(0.5, 0.09, 0.15, 0.03)[0],
    "8.2b": lambda: sharpe.mix_with_cash(0.5, 0.09, 0.15, 0.03)[1],
    "8.2c": lambda: sharpe.sharpe(*sharpe.mix_with_cash(0.5, 0.09, 0.15, 0.03), rf=0.03),
    "8.3": lambda: sharpe.annualize_sharpe(0.1, 252),
    "9.1a": lambda: drag.two_period_return(0.5, -0.5),
    "9.1b": lambda: drag.two_period_return(0.2, -0.2),
    "9.2a": lambda: drag.growth_rate(0.10, 0.20),
    "9.2b": lambda: drag.growth_rate(0.10, 0.40),
    "10.1": lambda: correlation.correlation_from_cov(0.02, 0.2, 0.2),
    "10.2": lambda: correlation.covariance([-1, 0, 1], [1, 0, 1]),
    "11.1": lambda: diversification.equal_weight_vol(0.2, 4, 0.0),
    "11.2a": lambda: diversification.equal_weight_vol(0.2, 4, 0.25),
    "11.2b": lambda: diversification.diversification_floor(0.2, 0.25),
    "11.figa": lambda: diversification.equal_weight_vol(0.2, 10, 0.3),
    "11.figb": lambda: diversification.equal_weight_vol(0.2, 100, 0.3),
    "11.figc": lambda: diversification.diversification_floor(0.2, 0.3),
    "12.1a": lambda: minvariance.two_asset_weight(0.10, 0.30, -1.0),
    "12.1b": lambda: minvariance.two_asset_vol(minvariance.two_asset_weight(0.10, 0.30, -1.0), 0.10, 0.30, -1.0),
    "13.1a": lambda: capm.beta_from_correlation(0.6, 0.30, 0.15),
    "13.1b": lambda: capm.expected_move(1.2, -0.04),
    "13.2": lambda: capm.capm_expected_return(0.03, 1.4, 0.08),
    "14.1": lambda: kelly.kelly_fraction(0.6, 1),
    "14.2a": lambda: kelly.kelly_fraction(0.4, 2),
    "14.2b": lambda: kelly.log_growth(0.10, 0.4, 2),
    "14.2c": lambda: kelly.log_growth(0.05, 0.4, 2),
    "14.2d": lambda: kelly.log_growth(0.05, 0.4, 2) / kelly.log_growth(0.10, 0.4, 2),
    "14.fig": lambda: kelly.kelly_fraction(0.55, 1),
    "15.1": lambda: montecarlo.paths_needed(0.4, 0.1, 10_000),
    "15.fig": lambda: montecarlo.median_growth(0.08, 0.20),
    "16.1a": lambda: _p5,
    "16.1b": lambda: tails.years_between(_p5, 252),
    "17.1": lambda: var.parametric_var(0.01, 1_000_000, 0.99),
    "17.2": lambda: var.parametric_es(0.01, 1_000_000, 0.99),
    "17.z": lambda: var.z_score(0.99),
    "17.es_mult": lambda: var.es_multiplier(0.99),
}


def load(path: Path | None = None) -> list[dict]:
    return json.loads(Path(path or FIXTURE_FILE).read_text())["rows"]


def reproduce(path: Path | None = None) -> list[dict]:
    """Every fixture with the library's answer: printed value, library value, tolerance, and whether it holds."""
    out = []
    for row in load(path):
        value = float(CALLS[row["id"]]())
        out.append(dict(id=row["id"], chapter=row["chapter"], quantity=row["quantity"], printed=row["printed"],
                        library=value, tol=row["tol"], phase0=row["computed"],
                        reproduces=abs(value - row["printed"]) <= row["tol"],
                        matches_phase0=math.isclose(value, row["computed"], rel_tol=1e-9, abs_tol=1e-12)))
    return out
