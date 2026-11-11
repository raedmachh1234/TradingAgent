"""The proposal state machine: the transition table itself, and the paths real proposals take."""
from __future__ import annotations

from collections import deque

import pytest

from quantbot.brokers.paper import PaperBroker
from quantbot.core.config import instruments
from quantbot.core.types import Mode, OrderType
from quantbot.execution.proposal import TERMINAL, TRANSITIONS, IllegalTransition, Proposal, State
from quantbot.risk.gate import RiskVerdict

from conftest import (T0, auto_cfg, awaiting, decide, decision, flat_feed, grant, make_cfg, make_orch, run_until, write_grants)

OWNER_STATES = {"PROPOSED", "RISK_PASSED", "AWAITING_HUMAN", "APPROVED", "REJECTED", "EDITED", "EXPIRED", "REVALIDATED",
                "SUBMITTED", "FILLED", "PARTIAL", "CANCELLED", "FAILED"}


def dummy(state: State) -> Proposal:
    from quantbot.core.types import Order
    d = decision()
    o = Order("c", "DEMO.A", d.side, 10, OrderType.MARKET, "s1", d.intent, "P1")
    v = RiskVerdict(o.fingerprint, True, (), T0, 1000, 20, 0.2, "t")
    p = Proposal("P1", d, o, Mode.M1, (), v, T0, T0, 100.0, 10000.0)
    p.state = state
    return p


def test_the_owners_states_and_edges_exist():
    assert OWNER_STATES <= {s.value for s in State}
    S = State
    for a, b in [(S.PROPOSED, S.RISK_PASSED), (S.RISK_PASSED, S.AWAITING_HUMAN), (S.AWAITING_HUMAN, S.APPROVED),
                 (S.AWAITING_HUMAN, S.REJECTED), (S.AWAITING_HUMAN, S.EDITED), (S.AWAITING_HUMAN, S.EXPIRED),
                 (S.APPROVED, S.REVALIDATED), (S.EDITED, S.REVALIDATED), (S.REVALIDATED, S.SUBMITTED),
                 (S.SUBMITTED, S.FILLED), (S.SUBMITTED, S.PARTIAL), (S.SUBMITTED, S.CANCELLED), (S.SUBMITTED, S.FAILED)]:
        assert b in TRANSITIONS[a], (a, b)


@pytest.mark.parametrize("src", list(State))
def test_every_transition_outside_the_table_is_refused(src):
    for dst in State:
        p = dummy(src)
        if dst in TRANSITIONS[src]:
            p.move(dst, T0)
            assert p.state is dst
        else:
            with pytest.raises(IllegalTransition):
                p.move(dst, T0)


def test_terminal_states_have_no_way_out():
    assert TERMINAL == {State.RISK_BLOCKED, State.OBSERVED, State.REJECTED, State.EXPIRED, State.FILLED, State.CANCELLED, State.FAILED}


def reachable(start: State, without: State | set[State]) -> set[State]:
    skip = without if isinstance(without, set) else {without}
    seen, todo = {start}, deque([start])
    while todo:
        for nxt in TRANSITIONS[todo.popleft()]:
            if nxt not in skip and nxt not in seen:
                seen.add(nxt)
                todo.append(nxt)
    return seen


@pytest.mark.parametrize("gate_state", [State.RISK_PASSED, State.REVALIDATED])
def test_nothing_reaches_the_broker_without_passing_risk_and_revalidation(gate_state):
    assert State.SUBMITTED not in reachable(State.PROPOSED, without=gate_state)


def test_a_proposal_waiting_for_a_human_reaches_the_broker_only_through_a_human_decision():
    assert State.SUBMITTED not in reachable(State.AWAITING_HUMAN, without={State.APPROVED, State.EDITED})
    assert State.SUBMITTED in reachable(State.AWAITING_HUMAN, without=set())


# ---- paths taken by real proposals ------------------------------------------------------------------------------
def path(p: Proposal) -> list[str]:
    return [s.value for _, s, _ in p.history]


def first_entry(orch) -> Proposal:
    return next(p for p in orch.approval.proposals.values() if p.decision.intent.value == "ENTRY")


def test_m1_path(tmp_path):
    orch, key = make_orch(tmp_path, make_cfg())
    steps = run_until(orch, flat_feed(), lambda o: awaiting(o))
    p = awaiting(orch)[0]
    assert decide(orch, key, p)
    orch.approval.tick()
    orch.step(*steps[0])
    assert path(p) == ["RISK_PASSED", "AWAITING_HUMAN", "APPROVED", "REVALIDATED", "SUBMITTED", "FILLED"]


def test_m3_path_needs_a_grant_and_then_goes_straight_through(tmp_path):
    cfg = auto_cfg("M3")
    orch, key = make_orch(tmp_path, cfg)
    write_grants(tmp_path / "g", key, [grant()])
    orch_g, _ = make_orch(tmp_path / "g", cfg, key)
    orch.run(flat_feed(6))
    orch_g.run(flat_feed(6))
    assert first_entry(orch).mode is Mode.M1  # no grant in this folder: capped
    assert path(first_entry(orch_g)) == ["RISK_PASSED", "APPROVED", "REVALIDATED", "SUBMITTED", "FILLED"]


def test_m0_and_risk_blocked_paths(tmp_path):
    orch, _ = make_orch(tmp_path, make_cfg(policy__default_mode="M0"))
    orch.run(flat_feed(6))
    assert path(first_entry(orch)) == ["RISK_PASSED", "OBSERVED"] and orch.executor.order_times == []
    blocked, _ = make_orch(tmp_path / "b", make_cfg(risk__max_order_notional=50))
    blocked.run(flat_feed(6))
    p = first_entry(blocked)
    assert path(p) == ["RISK_BLOCKED"] and "max_notional" in p.note


def test_partial_then_filled(tmp_path):
    cfg = make_cfg(costs__max_participation=5e-6)  # 5 units of each 1e6-volume bar; the order is for 10
    orch, key = make_orch(tmp_path, cfg)
    steps = run_until(orch, flat_feed(), lambda o: awaiting(o))
    p = awaiting(orch)[0]
    decide(orch, key, p)
    orch.approval.tick()
    orch.step(*steps[0])
    assert p.state is State.PARTIAL and p.filled_qty == 5
    orch.step(*steps[1])
    assert p.state is State.FILLED and path(p)[-2:] == ["PARTIAL", "FILLED"]


def test_broker_failure_ends_in_failed(tmp_path):
    cfg = make_cfg()
    broker = PaperBroker(instruments(cfg), **cfg["costs"])
    orch, key = make_orch(tmp_path, cfg, broker=broker)
    run_until(orch, flat_feed(), lambda o: awaiting(o))
    p = awaiting(orch)[0]
    broker.inject_failures(1)
    decide(orch, key, p)
    orch.approval.tick()
    assert p.state is State.FAILED and "outage" in p.note and orch.executor.error_times
