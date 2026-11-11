"""Allocator bake-off: the reference solver is right, every installed library agrees with it, and the stored
report follows the decision rule fixed before the first run."""
import itertools
import json
from pathlib import Path

import numpy as np
import pytest

from quantbot.foundation import allocators as a

REPORT = Path(__file__).resolve().parents[1] / "docs" / "phase2" / "allocator_bakeoff.json"


def _sharpe(w, mu, cov, rf):
    return (w @ mu - rf) / np.sqrt(w @ cov @ w)


def test_reference_max_sharpe_matches_a_brute_force_search():
    mu = np.array([0.008, 0.004, 0.006])
    cov = np.array([[0.0025, 0.0003, 0.0010], [0.0003, 0.0004, 0.0002], [0.0010, 0.0002, 0.0016]])
    w = a.reference("max_sharpe", mu, cov, rf=0.001, max_weight=0.6)
    step = 0.005
    best = max(((x, y, 1 - x - y) for x, y in itertools.product(np.arange(0, 0.6 + 1e-9, step), repeat=2)
                if 0 <= 1 - x - y <= 0.6 + 1e-9), key=lambda v: _sharpe(np.array(v), mu, cov, 0.001))
    assert _sharpe(w, mu, cov, 0.001) >= _sharpe(np.array(best), mu, cov, 0.001) - 1e-9
    assert w.sum() == pytest.approx(1.0) and (w <= 0.6 + 1e-9).all() and (w >= -1e-12).all()


def test_reference_refuses_when_nothing_beats_cash():
    with pytest.raises(ValueError):
        a.reference("max_sharpe", np.array([0.001, 0.0005]), np.eye(2) * 1e-4, rf=0.01)


def test_every_installed_library_agrees_with_the_reference():
    installed = [lib for lib, v in a.available().items() if v]
    if not installed:
        pytest.skip("no allocator library installed (pip install -e .[allocators])")
    result = a.compare(a.sample_returns(240, seed=3), repeats=1)
    for lib in installed:
        res = result["libraries"][lib]
        for problem, tol in a.PASS_TOL.items():
            assert "error" not in res[problem], res[problem]
            assert res[problem]["max_abs_diff"] <= tol, (lib, problem, res[problem]["max_abs_diff"])
            assert res[problem]["violation"] <= 1e-6


def test_decision_rule_ranks_features_then_footprint_then_speed():
    def lib(ms):
        return {"version": "1", "min_variance": {"median_ms": ms}, "max_sharpe": {"median_ms": ms}}

    fake = {"passes": {"A": True, "B": True, "C": False, "D": True},
            "comparison": {"libraries": {"A": lib(50), "B": lib(5), "C": lib(1), "D": lib(1)}},
            "features": {"A": dict.fromkeys(a.FEATURE_ORDER, True), "B": {"cvar": True},
                         "C": dict.fromkeys(a.FEATURE_ORDER, True), "D": {"cvar": True}},
            "footprint": {"A": ["x"] * 90, "B": ["x"] * 10, "C": [], "D": ["x"] * 10}}
    d = a.decide(fake)
    assert d["choice"] == "A"  # most features wins although slowest and heaviest; C failed
    assert [r["library"] for r in d["ranking"]] == ["A", "D", "B"]  # D and B tie on features and footprint


def test_stored_report_follows_the_rule():
    data = json.loads(REPORT.read_text())
    assert data["meta"]["decision"] == a.decide(data)
    assert data["meta"]["decision"]["choice"] == "skfolio"
    for lib, res in data["comparison"]["libraries"].items():
        assert data["passes"][lib] == all(res[p]["max_abs_diff"] <= tol and res[p]["violation"] <= 1e-6
                                          for p, tol in a.PASS_TOL.items())
