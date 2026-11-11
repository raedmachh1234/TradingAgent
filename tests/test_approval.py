"""ApprovalService: proposal expiry, price-drift revalidation, bounded edits, the M2 veto window."""
from __future__ import annotations

import pytest

from quantbot.core.types import Mode
from quantbot.execution.proposal import State

from conftest import (auto_cfg, awaiting, decide, feed, flat_feed, grant, make_bars, make_cfg, make_orch, run_until, write_grants)


def refused_reasons(orch):
    return [r["payload"]["reason"] for r in orch.log.records("HUMAN_DECISION_REFUSED")]


def open_proposal(tmp_path, cfg=None, closes=None):
    cfg = cfg or make_cfg()
    orch, key = make_orch(tmp_path, cfg)
    steps = feed(make_bars("DEMO.A", closes)) if closes else flat_feed()
    rest = run_until(orch, steps, lambda o: awaiting(o))
    return orch, key, awaiting(orch)[0], rest


# ---- expiry ----------------------------------------------------------------------------------------------------
def test_unanswered_proposal_expires_and_is_never_sent(tmp_path):
    orch, key, p, rest = open_proposal(tmp_path, make_cfg(execution__proposal_ttl_seconds=3600))
    orch.step(*rest[0])
    assert p.state is State.EXPIRED and orch.executor.order_times == []
    assert orch.result().vetoes["vetoed_or_expired"] == 1  # expired entries are tracked as counterfactuals


def test_an_approval_that_arrives_after_expiry_is_refused(tmp_path):
    orch, key, p, _ = open_proposal(tmp_path)
    orch.clock.set(p.expires_at)
    assert not decide(orch, key, p)
    assert p.state is State.EXPIRED and "expired" in refused_reasons(orch)[-1]
    orch.approval.tick()
    assert orch.executor.order_times == []


def test_expiry_does_not_apply_before_the_ttl(tmp_path):
    orch, key, p, rest = open_proposal(tmp_path)  # default ttl: four days
    orch.step(*rest[0])
    assert p.state is State.AWAITING_HUMAN and decide(orch, key, p)


# ---- price drift and revalidation ----------------------------------------------------------------------------------
def test_drift_beyond_tolerance_cancels_and_re_proposes_at_the_new_price(tmp_path):
    orch, key, p, rest = open_proposal(tmp_path, closes=[100, 100, 100] + [101] * 7)
    orch.step(*rest[0])                       # price moves 100 bps; tolerance is 50
    assert decide(orch, key, p)
    orch.approval.tick()
    assert p.state is State.CANCELLED and "price drift 100.0 bps" in p.note
    [q] = [x for x in orch.approval.proposals.values() if x.supersedes == p.id]
    assert q.state is State.AWAITING_HUMAN and q.reference_price == 101 and q.attempt == 1
    assert decide(orch, key, q)
    orch.approval.tick()
    assert q.state is State.SUBMITTED and len(orch.executor.order_times) == 1


def test_drift_within_tolerance_is_submitted(tmp_path):
    orch, key, p, rest = open_proposal(tmp_path, closes=[100, 100, 100] + [100.2] * 7)
    orch.step(*rest[0])
    decide(orch, key, p)
    orch.approval.tick()
    assert p.state is State.SUBMITTED


def test_re_proposals_are_limited(tmp_path):
    orch, key, p, rest = open_proposal(tmp_path, closes=[100, 100, 100, 101, 102, 102, 102, 102, 102, 102])
    orch.step(*rest[0])
    decide(orch, key, p)
    orch.approval.tick()
    q = next(x for x in orch.approval.proposals.values() if x.supersedes == p.id)
    orch.step(*rest[1])
    decide(orch, key, q)
    orch.approval.tick()
    assert q.state is State.CANCELLED
    assert not [x for x in orch.approval.proposals.values() if x.supersedes == q.id]  # max_reproposals = 1
    assert orch.executor.order_times == []


def test_stale_data_at_revalidation_cancels(tmp_path):
    cfg = make_cfg(risk__max_data_age_seconds=30 * 3600)
    orch, key = make_orch(tmp_path, cfg)
    steps = feed(make_bars("DEMO.A", [100] * 3), make_bars("DEMO.B", [50] * 5))  # DEMO.A stops after Wednesday
    rest = run_until(orch, steps, lambda o: awaiting(o))
    p = awaiting(orch)[0]
    for s in rest:
        orch.step(*s)                            # Thursday and Friday: no DEMO.A bar
    decide(orch, key, p)
    orch.approval.tick()
    assert p.state is State.CANCELLED and "data_fresh" in p.note and orch.executor.order_times == []
    q = next(x for x in orch.approval.proposals.values() if x.supersedes == p.id)
    assert q.state is State.RISK_BLOCKED


# ---- bounded edits -------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("edits, ok, message", [
    ({"quantity": 5}, True, ""),
    ({"quantity": 11}, False, "size can go down, never up"),
    ({"quantity": 0}, False, "below the minimum"),
    ({"quantity": 2.5}, False, "off the step"),
    ({"stop_price": 99.0}, True, ""),
    ({"stop_price": 97.0}, False, "closer to the entry"),
    ({"stop_price": 100.5}, False, "closer to the entry"),
    ({"target_price": 105.0}, True, ""),
    ({"target_price": 95.0}, False, "profit side"),
    ({"limit_price": 99.0}, False, "not a limit order"),
    ({"side": 1}, False, "unsupported fields"),
    ({}, False, "nothing to change"),
])
def test_edits_are_bounded(tmp_path, edits, ok, message):
    orch, key, p, _ = open_proposal(tmp_path)
    before = p.order
    assert decide(orch, key, p, "edit", edits=edits) is ok
    if ok:
        assert p.state is State.EDITED and p.edits == edits
        orch.approval.tick()
        assert p.state is State.SUBMITTED
        for field, value in edits.items():
            assert getattr(p.order, field) == value
        assert p.order.fingerprint != before.fingerprint
    else:
        assert p.state is State.AWAITING_HUMAN and p.order == before and message in refused_reasons(orch)[-1]


def test_an_edited_order_is_what_gets_filled(tmp_path):
    orch, key, p, rest = open_proposal(tmp_path)
    decide(orch, key, p, "edit", edits={"quantity": 4})
    orch.approval.tick()
    orch.step(*rest[0])
    assert p.state is State.FILLED and p.filled_qty == 4 and orch.ledger.strategy_position("s1", "DEMO.A") == 4


def test_only_the_size_of_an_exit_can_be_edited(tmp_path):
    orch, key, p, rest = open_proposal(tmp_path)
    decide(orch, key, p)
    orch.approval.tick()
    rest = run_until(orch, rest, lambda o: any(x.decision.intent.value == "EXIT" for x in awaiting(o)))
    ex = awaiting(orch)[0]
    assert not decide(orch, key, ex, "edit", edits={"target_price": 120.0})
    assert decide(orch, key, ex, "edit", edits={"quantity": 6})
    orch.approval.tick()
    orch.step(*rest[0])
    assert orch.ledger.strategy_position("s1", "DEMO.A") == 4


# ---- M2 veto window --------------------------------------------------------------------------------------------------
def veto_setup(tmp_path, key):
    cfg = auto_cfg("M2", policy__auto__veto_window_seconds=3600)
    write_grants(tmp_path, key, [grant(mode="M2")])
    orch, _ = make_orch(tmp_path, cfg, key)
    rest = run_until(orch, flat_feed(), lambda o: awaiting(o))
    return orch, awaiting(orch)[0], rest


def test_veto_window_executes_unless_vetoed(tmp_path, key):
    orch, p, rest = veto_setup(tmp_path, key)
    assert p.mode is Mode.M2 and p.state is State.AWAITING_VETO
    orch.step(*rest[0])
    assert [s.value for _, s, _ in p.history][-3:] == ["APPROVED", "REVALIDATED", "SUBMITTED"]


def test_a_veto_window_re_checks_the_m2_conditions_before_executing(tmp_path, key):
    orch, p, rest = veto_setup(tmp_path, key)
    orch.policy.auto["auto_limit_notional"] = 1.0  # the M2 conditions stop holding during the window
    orch.step(*rest[0])
    assert p.state is State.CANCELLED and "no longer hold" in p.note and orch.executor.order_times == []
    q = next(x for x in orch.approval.proposals.values() if x.supersedes == p.id)
    assert q.mode is Mode.M1 and q.state is State.AWAITING_HUMAN


def test_a_veto_inside_the_window_rejects(tmp_path, key):
    orch, p, rest = veto_setup(tmp_path, key)
    assert not decide(orch, key, p, "approve")  # nothing to approve during a veto window
    assert decide(orch, key, p, "reject", reason="not today")
    orch.step(*rest[0])
    assert p.state is State.REJECTED and p.reject_reason == "not today" and orch.executor.order_times == []
