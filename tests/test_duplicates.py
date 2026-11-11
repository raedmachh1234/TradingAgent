"""Duplicate-order protection at every layer."""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from quantbot.brokers.paper import PaperBroker
from quantbot.core.config import instruments
from quantbot.core.types import Intent, Side
from quantbot.execution.proposal import State

from conftest import auto_cfg, awaiting, decide, decision, flat_feed, grant, make_cfg, make_orch, run_until, write_grants


def setup(tmp_path, key, cfg=None):
    cfg = cfg or make_cfg()
    broker = PaperBroker(instruments(cfg), **cfg["costs"])
    orch, _ = make_orch(tmp_path, cfg, key, broker=broker)
    rest = run_until(orch, flat_feed(), lambda o: awaiting(o))
    return orch, broker, awaiting(orch)[0], rest


def test_the_same_decision_delivered_twice_makes_one_proposal(tmp_path, key):
    orch, broker, p, _ = setup(tmp_path, key)
    n = len(orch.approval.proposals)
    orch.submit_decision(p.decision)
    assert len(orch.approval.proposals) == n and orch.log.records("DECISION_DUPLICATE")


def test_the_same_approval_delivered_twice_sends_one_order(tmp_path, key):
    orch, broker, p, rest = setup(tmp_path, key)
    assert decide(orch, key, p) and decide(orch, key, p)
    orch.approval.tick()
    orch.approval.tick()
    orch.step(*rest[0])
    assert len(broker.accepted) == 1 and orch.ledger.strategy_position("s1", "DEMO.A") == 10
    assert orch.log.records("HUMAN_DECISION_DUPLICATE")


def test_a_second_entry_while_one_is_pending_is_skipped(tmp_path, key):
    orch, broker, p, _ = setup(tmp_path, key)
    later = replace(p.decision, ts=p.decision.ts + timedelta(hours=1), quantity=7)
    orch.submit_decision(later)
    assert any("already pending" in r["payload"]["reason"] for r in orch.log.records("DECISION_SKIPPED"))
    assert sum(x.decision.intent is Intent.ENTRY for x in orch.approval.proposals.values()) == 1


def test_the_executor_and_the_broker_deduplicate_client_order_ids(tmp_path, key):
    orch, broker, p, _ = setup(tmp_path, key)
    decide(orch, key, p)
    orch.approval.tick()
    assert p.state is State.SUBMITTED
    v = orch.risk.check(p.order, orch.gate.snapshot(p.order, p.id))
    again = orch.executor.submit(p.order, v)
    assert again.duplicate and len(broker.accepted) == 1
    # a restarted executor has forgotten its acknowledgements; the broker still refuses the repeat
    assert broker.submit(p.order).duplicate and len(broker.accepted) == 1


def test_client_order_ids_are_deterministic_across_restarts(tmp_path, key):
    a, _, pa, _ = setup(tmp_path / "a", key)
    b, _, pb, _ = setup(tmp_path / "b", key)
    assert pa.order.client_order_id == pb.order.client_order_id and pa.id == pb.id


def test_two_identical_exits_cannot_both_be_pending(tmp_path, key):
    write_grants(tmp_path, key, [grant()])
    orch, _ = make_orch(tmp_path, auto_cfg("M1"), key)
    rest = run_until(orch, flat_feed(), lambda o: awaiting(o))
    decide(orch, key, awaiting(orch)[0])
    orch.approval.tick()
    orch.step(*rest[0])  # entry filled
    ex1 = decision(side=Side.SELL, intent=Intent.EXIT, stop=None, ts=orch.clock.now())
    ex2 = replace(ex1, ts=orch.clock.now() + timedelta(seconds=1))
    orch.submit_decision(ex1)
    orch.submit_decision(ex2)
    states = [x.state for x in orch.approval.proposals.values() if x.decision.intent is Intent.EXIT]
    assert states == [State.AWAITING_HUMAN, State.RISK_BLOCKED]
    blocked = next(x for x in orch.approval.proposals.values() if x.state is State.RISK_BLOCKED)
    assert "duplicate" in blocked.note
