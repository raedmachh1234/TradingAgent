"""The risk gate's rules, entry/exit asymmetry, and the executor refusing anything without a genuine verdict."""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from quantbot.brokers.paper import PaperBroker
from quantbot.core.bus import EventBus
from quantbot.core.clock import SimClock
from quantbot.core.config import load_config
from quantbot.core.eventlog import EventLog
from quantbot.core.types import Instrument, Intent, Order, OrderType, Side
from quantbot.execution.executor import ExecutionRefused, Executor
from quantbot.risk.gate import RiskGate, RiskLimits, RiskSnapshot
from quantbot.risk.killswitch import KillSwitch

from conftest import T0

INST = Instrument("DEMO.A")


def limits(**kw):
    risk = load_config(read_user_file=False)["risk"]
    risk.update(kw)
    return RiskLimits.from_config(risk)


def gate(**kw):
    return RiskGate(limits(**kw), KillSwitch())


def snap(**kw):
    base = dict(now=T0, equity=10000.0, cash=10000.0, day_pnl=0.0, drawdown_pct=0.0, price=100.0, data_age_seconds=0.0,
                instrument=INST, strategy_position=0.0, strategy_capital=10000.0, strategy_exposure=0.0, gross_exposure=0.0,
                position_notional=0.0, open_positions=0, strategy_open_positions=0)
    base.update(kw)
    return RiskSnapshot(**base)


def entry(qty=10, stop=98.0, side=Side.BUY, symbol="DEMO.A", **kw):
    return Order("c1", symbol, side, qty, OrderType.MARKET, "s1", Intent.ENTRY, "P1", None, stop, None, **kw)


def exit_(qty=10, side=Side.SELL):
    return Order("c2", "DEMO.A", side, qty, OrderType.MARKET, "s1", Intent.EXIT, "P2")


def blocked(v):
    return {c.name for c in v.checks if not c.passed and c.blocking}


def warned(v):
    return {c.name for c in v.checks if not c.passed and not c.blocking}


def test_a_normal_entry_passes_and_reports_its_worst_case():
    v = gate().check(entry(), snap())
    assert v.passed and v.notional == 1000 and v.worst_case_loss == pytest.approx(20) and v.worst_case_loss_pct == pytest.approx(0.2)


@pytest.mark.parametrize("order, s, rule", [
    (entry(stop=None), snap(), "stop_required"),
    (entry(stop=101.0), snap(), "stop_side"),
    (entry(qty=20, stop=90.0), snap(), "risk_per_trade"),
    (entry(qty=30, stop=99.0), snap(), "max_notional"),
    (entry(qty=1, stop=4.9), snap(price=5.0), "min_notional"),
    (entry(qty=10), snap(position_notional=2000.0), "position_size"),
    (entry(qty=10), snap(gross_exposure=9500.0), "gross_exposure"),
    (entry(qty=10), snap(open_positions=5), "open_positions"),
    (entry(qty=10), snap(strategy_capital=1000.0, strategy_exposure=500.0), "strategy_capital"),
    (entry(qty=10), snap(strategy_open_positions=3), "strategy_open_positions"),
    (entry(qty=10), snap(cash=500.0), "cash"),
    (entry(side=Side.SELL, stop=102.0), snap(), "short"),
    (entry(qty=10), snap(day_pnl=-300.0, equity=9700.0), "daily_loss"),
    (entry(qty=10), snap(drawdown_pct=12.0), "drawdown"),
    (entry(qty=10), snap(data_age_seconds=10 * 86400.0), "data_fresh"),
    (entry(qty=10), snap(data_age_seconds=None), "data_fresh"),
    (entry(qty=10), snap(data_ok=False), "data_fresh"),
    (entry(qty=10), snap(reconciled=False), "reconciled"),
    (entry(qty=10), snap(halted=True), "halt"),
    (entry(qty=2.5), snap(), "quantity"),
    (entry(qty=10), snap(recent_order_times=tuple(T0 - timedelta(seconds=i) for i in range(6))), "order_rate"),
    (entry(qty=10), snap(orders_today=30), "orders_per_day"),
    (entry(qty=10), snap(price=None), "instrument"),
])
def test_each_entry_rule_blocks(order, s, rule):
    v = gate().check(order, s)
    assert not v.passed and rule in blocked(v), (rule, v.blocks())


def test_blocked_symbol_and_duplicate():
    assert "blocked_symbol" in blocked(gate(blocked_symbols=["DEMO.A"]).check(entry(), snap()))
    o = entry()
    assert "duplicate" in blocked(gate().check(o, snap(active_fingerprints=frozenset({o.fingerprint}))))


def test_exits_stay_possible_when_entries_are_blocked():
    bad_day = snap(strategy_position=10.0, day_pnl=-300.0, equity=9700.0, drawdown_pct=12.0, halted=True, reconciled=False,
                   data_age_seconds=10 * 86400.0)
    v = gate().check(exit_(), bad_day)
    assert v.passed and {"daily_loss", "drawdown", "halt", "reconciled", "data_fresh"} <= warned(v)
    assert not gate().check(entry(), bad_day).passed


def test_exit_hard_rules_still_apply():
    assert "exit_reduces" in blocked(gate().check(exit_(qty=11), snap(strategy_position=10.0)))
    assert "exit_reduces" in blocked(gate().check(exit_(), snap(strategy_position=0.0)))
    assert "exit_reduces" in blocked(gate().check(exit_(side=Side.BUY), snap(strategy_position=10.0)))


def test_kill_switch_blocks_entries_and_by_default_allows_exits():
    g = gate()
    g.kill_switch.engage("drill", "test", T0)
    assert "kill_switch" in blocked(g.check(entry(), snap()))
    assert g.check(exit_(), snap(strategy_position=10.0)).passed
    strict = gate(kill_switch_allows_exits=False)
    strict.kill_switch.engage("drill", "test", T0)
    assert "kill_switch" in blocked(strict.check(exit_(), snap(strategy_position=10.0)))


# ---- the executor only accepts genuine, fresh, passing verdicts for exactly that order -------------------------------
def make_executor():
    clock = SimClock(T0)
    g = gate()
    broker = PaperBroker({"DEMO.A": INST})
    ex = Executor(broker, g, clock, EventBus(EventLog(), clock), verdict_max_age_seconds=5)
    return ex, g, clock, broker


def test_executor_accepts_a_genuine_verdict():
    ex, g, _, broker = make_executor()
    o = entry()
    assert ex.submit(o, g.check(o, snap())).accepted and len(broker.accepted) == 1


@pytest.mark.parametrize("attack", ["other_gate", "other_order", "stale", "blocked", "forged_flag", "none"])
def test_executor_refuses_bad_verdicts(attack):
    ex, g, clock, broker = make_executor()
    o = entry()
    if attack == "other_gate":
        v = gate().check(o, snap())                                  # signed with another gate's secret
    elif attack == "other_order":
        v = g.check(entry(qty=5), snap())                            # genuine, but for a different order
    elif attack == "stale":
        v = g.check(o, snap())
        clock.set(T0 + timedelta(seconds=6))
    elif attack == "blocked":
        v = g.check(entry(stop=None), snap())
        o = entry(stop=None)
    elif attack == "forged_flag":
        v = replace(g.check(entry(stop=None), snap()), passed=True)  # flip a block into a pass
        o = entry(stop=None)
    else:
        v = None
    with pytest.raises(ExecutionRefused):
        ex.submit(o, v)
    assert broker.accepted == []


def test_executor_enforces_kill_switch_and_order_rate_itself():
    ex, g, clock, broker = make_executor()
    o = entry()
    v = g.check(o, snap())
    g.kill_switch.engage("drill", "test", T0)
    with pytest.raises(ExecutionRefused, match="kill switch"):
        ex.submit(o, v)
    g.kill_switch._memory = None  # test-only reset; real release needs a signed operator command
    ex.order_times = [T0] * 6
    with pytest.raises(ExecutionRefused, match="order rate"):
        ex.submit(o, v)
