"""Replaying the same data in M0, M1, M2 and M3 gives identical decisions; only what happens after them differs."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from quantbot.core.clock import SimClock
from quantbot.data.providers import SyntheticProvider
from quantbot.data.service import DataService, replay_feed
from quantbot.data.store import DataStore
from quantbot.execution.proposal import State
from quantbot.execution.scripted import ScriptedHuman, approve_all

from conftest import auto_cfg, grant, make_cfg, make_orch, write_grants

UTC = timezone.utc
START, END = datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 12, 31, tzinfo=UTC)
STRATEGIES = [
    {"id": "ma", "class": "ma_crossover", "version": "0.1.0", "symbols": ["DEMO.A", "DEMO.B"], "weight": 2.0,
     "params": {"fast": 10, "slow": 30, "atr_window": 14, "stop_atr": 2.0, "target_r": 2.0, "risk_pct": 0.5}},
    {"id": "rnd", "class": "random_entry", "version": "0.1.0", "symbols": ["DEMO.B"], "weight": 1.0,
     "params": {"seed": 3, "entry_probability": 0.15, "hold_bars": 4, "notional_pct": 10.0, "stop_pct": 3.0}},
]


@pytest.fixture(scope="module")
def bars(tmp_path_factory):
    store = DataStore(tmp_path_factory.mktemp("cache"))
    svc = DataService(store, [SyntheticProvider(seed=7)], SimClock(datetime(2026, 1, 1, tzinfo=UTC)))
    for s in ("DEMO.A", "DEMO.B"):
        svc.ensure_bars("demo", s, START, END)
    return list(replay_feed(store, "demo", ["DEMO.A", "DEMO.B"]))


def mixed_human(key):
    seen = {}

    def rule(p):
        n = seen.setdefault(p.id, len(seen) + 1)
        if p.decision.intent.value == "EXIT":
            return "approve", {}
        if n % 3 == 0:
            return "reject", {"reason": "test"}
        if n % 4 == 0:
            return "edit", {"edits": {"quantity": max(1.0, float(int(p.order.quantity / 2)))}}
        if n % 5 == 0:
            return "ignore", {}
        return "approve", {}

    return ScriptedHuman(key, rule)


def run(tmp_path, key, bars, mode, human=None):
    base = tmp_path / mode
    if mode in ("M2", "M3"):
        write_grants(base, key, [grant("ma", mode), grant("rnd", mode)])
        cfg = auto_cfg(mode, STRATEGIES)
    else:
        cfg = make_cfg(STRATEGIES, policy__default_mode="M0" if mode == "M0" else "M1")
    orch, _ = make_orch(base, cfg, key, start=datetime(2024, 12, 1, tzinfo=UTC))
    return orch, orch.run(bars, human=human)


def test_decisions_are_identical_in_every_mode(tmp_path, key, bars):
    results = {
        "M0": run(tmp_path, key, bars, "M0"),
        "M1": run(tmp_path, key, bars, "M1", ScriptedHuman(key, approve_all)),
        "M1-mixed": run(tmp_path, key, bars, "M1", mixed_human(key)),
        "M2": run(tmp_path, key, bars, "M2"),
        "M3": run(tmp_path, key, bars, "M3"),
    }
    hashes = {name: r.decision_hash for name, (_, r) in results.items()}
    counts = {name: len(r.decision_ids) for name, (_, r) in results.items()}
    assert len(set(hashes.values())) == 1, hashes
    assert min(counts.values()) > 20, counts
    orders = {name: r.orders_sent for name, (_, r) in results.items()}
    assert orders["M0"] == 0 and orders["M3"] > 20 and orders["M1-mixed"] < orders["M1"]
    o_mixed = results["M1-mixed"][0]
    states = {p.state for p in o_mixed.approval.proposals.values()}
    assert {State.REJECTED, State.FILLED} <= states and any(p.edits for p in o_mixed.approval.proposals.values())
    modes = {name: {p.mode.name for p in o.approval.proposals.values()} for name, (o, _) in results.items()}
    assert modes["M0"] == {"M0"} and modes["M1"] == {"M1"} and modes["M2"] == {"M2"} and modes["M3"] == {"M3"}


def test_m1_approving_everything_at_once_trades_like_m3(tmp_path, key, bars):
    _, r1 = run(tmp_path, key, bars, "M1", ScriptedHuman(key, approve_all))
    _, r3 = run(tmp_path, key, bars, "M3")
    assert r1.orders_sent == r3.orders_sent and r1.fills == r3.fills and r1.equity == r3.equity


def test_a_replay_is_fully_deterministic(tmp_path, key, bars):
    _, a = run(tmp_path / "a", key, bars, "M3")
    _, b = run(tmp_path / "b", key, bars, "M3")
    assert (a.decision_hash, a.orders_sent, a.fills, a.equity, a.proposal_states) == \
           (b.decision_hash, b.orders_sent, b.fills, b.equity, b.proposal_states)


def test_the_shadow_book_does_not_depend_on_the_mode(tmp_path, key, bars):
    _, r0 = run(tmp_path, key, bars, "M0")
    _, r3 = run(tmp_path, key, bars, "M3")
    assert r0.shadow_equity == r3.shadow_equity and r0.equity == 10000.0
