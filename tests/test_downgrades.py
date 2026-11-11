"""Every downgrade trigger lowers autonomy (to M1, or halt), and only a signed operator command lifts it."""
from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from quantbot.brokers.paper import PaperBroker
from quantbot.core.config import instruments
from quantbot.core.types import Fill, Intent, Mode, Side
from quantbot.execution import signing
from quantbot.execution.policy import PolicyContext
from quantbot.execution.proposal import State
from quantbot.portfolio.ledger import Ledger

from conftest import (T0, auto_cfg, decision, feed, flat_feed, grant, make_bars, make_orch, run_until, sched,
                      write_grants)

ENTRY = decision()
EXIT = decision(side=Side.SELL, intent=Intent.EXIT, stop=None)
CTX = PolicyContext(T0, 100.0, True, True, True)


@pytest.fixture
def granted(tmp_path, key):
    write_grants(tmp_path, key, [grant(mode="M3")])
    orch, _ = make_orch(tmp_path, auto_cfg("M3"), key)
    assert orch.policy.resolve(ENTRY, CTX).mode is Mode.M3
    return orch, key


def calm_ledger(orch):
    return Ledger(10000, orch.instruments)


def slip_fill(price=100.5, expected=100.0):
    return Fill("c", "DEMO.A", Side.BUY, 10, price, T0, 0.0, "s1", Intent.ENTRY, "P", "order", expected)


# trigger name -> how to provoke it, then (entry mode, exit mode) afterwards with the default actions
TRIGGERS = {
    "daily_loss": (lambda o, led: setattr(led, "cash", 9700.0), Mode.M0, Mode.M1),
    "drawdown": (lambda o, led: (setattr(led, "high_water", 12000.0), setattr(led, "day_start_equity", 10000.0)), Mode.M0, Mode.M1),
    "stale_data": ("stale", Mode.M1, Mode.M1),
    "bad_data": ("bad", Mode.M1, Mode.M1),
    "reconciliation": ("unreconciled", Mode.M0, Mode.M1),
    "broker_errors": ("errors", Mode.M1, Mode.M1),
    "slippage": (lambda o, led: [o.monitors.record_fill(slip_fill()) for _ in range(5)], Mode.M1, Mode.M1),
    "calibration": (lambda o, led: o.monitors.record_calibration("s1", 0.30, 0.20), Mode.M1, Mode.M1),
    "kill_switch": (lambda o, led: o.kill.engage("drill", "test", T0), Mode.M0, Mode.M1),
}


@pytest.mark.parametrize("trigger", list(TRIGGERS))
def test_each_trigger_downgrades_and_never_raises(granted, trigger):
    orch, key = granted
    how, entry_mode, exit_mode = TRIGGERS[trigger]
    led = calm_ledger(orch)
    kw = {}
    if how == "stale":
        kw["stale_symbols"] = ["DEMO.A"]
    elif how == "bad":
        kw["bad_symbols"] = ["DEMO.A"]
    elif how == "unreconciled":
        kw["reconciled"] = False
    elif how == "errors":
        kw["broker_error_times"] = [T0 - timedelta(seconds=s) for s in (1, 2, 3)]
    else:
        how(orch, led)
    fired = orch.monitors.evaluate(T0, led, **kw)
    assert fired == [trigger]
    assert orch.monitors.evaluate(T0, led, **kw) == []          # fires once, stays in force
    assert orch.policy.resolve(ENTRY, CTX).mode is entry_mode
    assert orch.policy.resolve(EXIT, CTX).mode is exit_mode
    assert orch.log.records("DOWNGRADE")[-1]["payload"]["trigger"] == trigger


def test_quiet_conditions_fire_nothing(granted):
    orch, _ = granted
    led = calm_ledger(orch)
    orch.monitors.record_fill(slip_fill(100.01))
    orch.monitors.record_calibration("s1", 0.21, 0.20)
    assert orch.monitors.evaluate(T0, led, broker_error_times=[T0, T0 - timedelta(hours=1)]) == []


def command(key, action, orch, scope="global", age=timedelta(0)):
    return signing.sign_command(key, action, scope, orch.clock.now() - age, uuid.uuid4().hex)


def test_downgrades_are_lifted_only_by_a_signed_operator_command(granted):
    orch, key = granted
    orch.kill.engage("drill", "test", T0)
    orch.monitors.evaluate(T0, calm_ledger(orch))
    assert orch.policy.halted
    stranger = signing.generate_private_key()
    assert not orch.operator_command(command(stranger, "release_kill_switch", orch))[0]
    assert not orch.operator_command(command(key, "clear_downgrade", orch, age=timedelta(hours=1)))[0]  # too old
    assert orch.kill.engaged and orch.policy.halted
    assert orch.operator_command(command(key, "release_kill_switch", orch))[0] and not orch.kill.engaged
    assert orch.policy.halted                                      # releasing the switch does not lift the halt by itself
    lift = command(key, "clear_downgrade", orch)
    assert orch.operator_command(lift)[0] and not orch.policy.halted
    assert orch.policy.resolve(ENTRY, CTX).mode is Mode.M3          # back to what the signed grant allows, never more
    assert not orch.operator_command(lift)[0]                       # a command works once
    assert [r["payload"]["ok"] for r in orch.log.records("OPERATOR_COMMAND")] == [False, False, True, True, False]


def test_a_used_command_stays_used_after_a_restart(tmp_path, key):
    write_grants(tmp_path, key, [grant(mode="M3")])
    orch, _ = make_orch(tmp_path, auto_cfg("M3"), key, log=True)
    cmd = command(key, "clear_downgrade", orch)
    assert orch.operator_command(cmd)[0]
    again, _ = make_orch(tmp_path, auto_cfg("M3"), key, log=True)
    assert not again.operator_command(cmd)[0]


def test_a_strategy_scoped_downgrade_leaves_other_strategies_alone(tmp_path, key):
    write_grants(tmp_path, key, [grant("s1", "M3"), grant("s2", "M3")])
    orch, _ = make_orch(tmp_path, auto_cfg("M3", [sched("s1"), sched("s2", ("DEMO.B",))]), key)
    orch.monitors.record_calibration("s1", 0.5, 0.2)
    orch.monitors.evaluate(T0, calm_ledger(orch))
    assert orch.policy.resolve(ENTRY, CTX).mode is Mode.M1
    assert orch.policy.resolve(decision(symbol="DEMO.B", sid="s2"), CTX).mode is Mode.M3


# ---- the same triggers, provoked through a running orchestrator ------------------------------------------------------
def test_daily_loss_in_a_live_replay_halts_entries(tmp_path, key):
    write_grants(tmp_path, key, [grant(mode="M3")])
    cfg = auto_cfg("M3", [sched(qty=25, stop_pct=20.0, exit_at=9)], risk__max_risk_per_trade_pct=10.0)
    orch, _ = make_orch(tmp_path, cfg, key)
    orch.run(feed(make_bars("DEMO.A", [100, 100, 100, 100, 90, 90, 90, 90, 90, 90, 90])))
    assert "daily_loss" in orch.policy.downgrades()["halted"]
    ex = next(p for p in orch.approval.proposals.values() if p.decision.intent is Intent.EXIT)
    assert ex.mode is Mode.M1 and "halted by daily_loss" in " ".join(ex.mode_reasons)


def test_kill_file_created_by_hand_halts_trading(tmp_path, key):
    kill = tmp_path / "KILL"
    orch, _ = make_orch(tmp_path, auto_cfg("M1"), key, kill_file=kill)
    steps = flat_feed()
    orch.step(*steps[0])
    kill.write_text("stop everything\n")
    run_until(orch, steps[1:], lambda o: bool(o.approval.proposals))
    p = next(iter(orch.approval.proposals.values()))
    assert orch.policy.halted and p.state is State.RISK_BLOCKED and "kill switch" in p.note


def test_reconciliation_mismatch_halts_and_blocks_entries(tmp_path, key):
    cfg = auto_cfg("M1", [sched(enter_at=5)])
    broker = PaperBroker(instruments(cfg), **cfg["costs"])
    orch, _ = make_orch(tmp_path, cfg, key, broker=broker)
    steps = flat_feed()
    orch.step(*steps[0])
    broker.tamper_position("DEMO.A", 3)  # someone traded on the account behind the gate's back
    orch.run(steps[1:6])
    assert not orch.reconciler.ok and "reconciliation" in orch.policy.downgrades()["halted"]
    p = next(iter(orch.approval.proposals.values()))
    assert p.state is State.RISK_BLOCKED and "reconciled" in p.note
    assert orch.log.records("RECONCILIATION")[0]["payload"]["mismatches"][0]["broker"] == 3


def test_stale_data_in_a_replay_caps_an_m3_strategy_at_m1(tmp_path, key):
    write_grants(tmp_path, key, [grant("s1", "M3"), grant("s2", "M3")])
    cfg = auto_cfg("M3", [sched("s1"), sched("s2", ("DEMO.B",), enter_at=6)], risk__max_data_age_seconds=30 * 3600)
    orch, _ = make_orch(tmp_path, cfg, key)
    orch.run(feed(make_bars("DEMO.A", [100] * 2), make_bars("DEMO.B", [50] * 8)))
    assert "stale_data" in orch.policy.downgrades()["global_m1"]
    p = next(p for p in orch.approval.proposals.values() if p.order.symbol == "DEMO.B")
    assert p.mode is Mode.M1 and p.state is State.AWAITING_HUMAN


def test_repeated_broker_errors_in_a_replay(tmp_path, key):
    write_grants(tmp_path, key, [grant(f"s{i}", "M3") for i in range(3)])
    strategies = [sched(f"s{i}", ("DEMO.A",), qty=5) for i in range(3)]
    cfg = auto_cfg("M3", strategies)
    broker = PaperBroker(instruments(cfg), **cfg["costs"])
    broker.inject_failures(3)
    orch, _ = make_orch(tmp_path, cfg, key, broker=broker)
    orch.run(flat_feed(6))
    assert sum(p.state is State.FAILED for p in orch.approval.proposals.values()) == 3
    assert "broker_errors" in orch.policy.downgrades()["global_m1"]
