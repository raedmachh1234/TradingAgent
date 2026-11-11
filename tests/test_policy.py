"""PolicyEngine and signed grants: the strictest rule wins, and nothing the bot controls can raise its own mode."""
from __future__ import annotations

from datetime import timedelta

import pytest
import yaml

from quantbot.brokers.base import PROORDER_LIVE_SCRIPT, PROREALTIME_TICKET, BrokerCapabilities
from quantbot.core.types import Mode
from quantbot.execution import signing
from quantbot.execution.policy import GrantStore, PolicyContext, PolicyEngine

from conftest import T0, auto_cfg, decision, grant, make_cfg, write_grants

PAPER = BrokerCapabilities("paper", frozenset(Mode), is_paper=True)


def engine(tmp_path, cfg, key=None, grants=None, adapter=PAPER, now=T0 - timedelta(days=10), pinned=None):
    if key is not None and grants is not None:
        write_grants(tmp_path, key, grants)
    events = []
    gs = GrantStore(tmp_path / "config/autonomy.yaml", tmp_path / "config/operator.pub", cfg["autonomy"]["cooling_off_hours"],
                    sink=lambda t, p: events.append((t, p)), pinned_fingerprint=pinned)
    gs.reload(now)
    return PolicyEngine(cfg, gs, adapter), events


def ctx(now=T0, notional=1000.0, risk_passed=True, fresh=True, reconciled=True):
    return PolicyContext(now, notional, risk_passed, fresh, reconciled)


def mode(pe, d=None, **kw):
    return pe.resolve(d or decision(), ctx(**kw)).mode


# ---- rules -------------------------------------------------------------------------------------------------------
def test_the_strictest_matching_rule_wins(tmp_path, key):
    cfg = make_cfg()
    cfg["policy"]["rules"] = [{"name": "bot", "match": {"strategy": "s*"}, "mode": "M3"},
                              {"name": "big", "match": {"notional_gte": 5000}, "mode": "M1"},
                              {"name": "dax", "match": {"instrument": "DEMO.B"}, "mode": "M0"},
                              {"name": "wild", "match": {"regime": ["high_vol"]}, "mode": "M1"},
                              {"name": "night", "match": {"time": {"timezone": "UTC", "outside": "08:00-20:00"}}, "mode": "M2"}]
    pe, _ = engine(tmp_path, cfg, key, [grant(mode="M3")])
    noon = T0.replace(hour=12)
    assert mode(pe, now=noon) is Mode.M3
    assert mode(pe, now=noon, notional=6000) is Mode.M1
    assert mode(pe, decision(symbol="DEMO.B"), now=noon) is Mode.M0
    assert mode(pe, decision(regime="high_vol"), now=noon) is Mode.M1
    assert mode(pe, now=T0, notional=100.0) is Mode.M2  # 21:00 UTC is outside 08:00-20:00
    assert mode(pe, now=T0, notional=1000.0) is Mode.M1  # ...and above the default auto limit, M2 falls back to M1


def test_unknown_rule_keys_are_rejected(tmp_path):
    cfg = make_cfg()
    cfg["policy"]["rules"] = [{"name": "typo", "match": {"strategi": "s1"}, "mode": "M0"}]
    with pytest.raises(ValueError, match="unknown match keys"):
        engine(tmp_path, cfg)


# ---- the bot cannot escalate its own mode -------------------------------------------------------------------------
def test_without_a_signed_grant_everything_is_capped_at_m1(tmp_path):
    pe, _ = engine(tmp_path, auto_cfg("M3"))
    r = pe.resolve(decision(), ctx())
    assert r.mode is Mode.M1 and "no signed grant" in r.reasons[-1]


def test_a_grant_signed_by_another_key_is_rejected(tmp_path, key):
    write_grants(tmp_path, signing.generate_private_key(), [grant()])  # signed by someone else...
    signing.save_public_key(key.public_key(), tmp_path / "config/operator.pub")  # ...but the operator key is installed
    pe, events = engine(tmp_path, auto_cfg("M3"))
    assert mode(pe) is Mode.M1 and pe.grants.status.startswith("grants rejected")
    assert events[-1][0] == "GRANT_REJECTED"


@pytest.mark.parametrize("tamper", ["raise_mode", "add_strategy", "drop_signature", "change_date"])
def test_a_grant_edited_after_signing_is_rejected(tmp_path, key, tamper):
    write_grants(tmp_path, key, [grant(mode="M2")])
    f = tmp_path / "config/autonomy.yaml"
    doc = yaml.safe_load(f.read_text())
    if tamper == "raise_mode":
        doc["grants"][0]["max_mode"] = "M3"
    elif tamper == "add_strategy":
        doc["grants"].append(grant("s2", "M3"))
    elif tamper == "drop_signature":
        doc.pop("signature")
    else:
        doc["grants"][0]["signed_at"] = "2020-01-01T00:00:00+00:00"
    f.write_text(yaml.safe_dump(doc))
    pe, _ = engine(tmp_path, auto_cfg("M3"))
    assert mode(pe) is Mode.M1


def test_a_valid_grant_caps_at_its_own_level(tmp_path, key):
    pe, _ = engine(tmp_path, auto_cfg("M3"), key, [grant(mode="M2")])
    r = pe.resolve(decision(), ctx())
    assert r.mode is Mode.M2 and "capped at M2" in r.reasons[-1]


def test_cooling_off_runs_from_when_the_bot_first_sees_the_grant(tmp_path, key):
    # signed_at is in the distant past; it does not let a grant skip its cooling-off period
    pe, _ = engine(tmp_path, auto_cfg("M3"), key, [grant(mode="M3", signed_at="2020-01-01T00:00:00+00:00")], now=T0)
    assert mode(pe, now=T0 + timedelta(hours=71)) is Mode.M1
    assert "cooling off" in pe.resolve(decision(), ctx(now=T0 + timedelta(hours=71))).reasons[-1]
    assert mode(pe, now=T0 + timedelta(hours=72)) is Mode.M3


def test_cooling_off_survives_a_restart_through_the_audit_log(tmp_path, key):
    write_grants(tmp_path, key, [grant(mode="M3")])
    events = []
    first = GrantStore(tmp_path / "config/autonomy.yaml", tmp_path / "config/operator.pub", {"M2": 24, "M3": 72},
                       sink=lambda t, p: events.append({"type": t, "payload": p}))
    first.reload(T0)
    again = GrantStore(tmp_path / "config/autonomy.yaml", tmp_path / "config/operator.pub", {"M2": 24, "M3": 72})
    again.restore(events)
    again.reload(T0 + timedelta(hours=70))  # a restart late in the period does not restart the clock...
    assert again.max_mode("s1", T0 + timedelta(hours=72))[0] is Mode.M3
    fresh = GrantStore(tmp_path / "config/autonomy.yaml", tmp_path / "config/operator.pub", {"M2": 24, "M3": 72})
    fresh.reload(T0 + timedelta(hours=70))  # ...and without the log it can only get stricter
    assert fresh.max_mode("s1", T0 + timedelta(hours=72))[0] is Mode.M1


def test_expired_grant_and_pinned_key(tmp_path, key):
    pe, _ = engine(tmp_path, auto_cfg("M3"), key, [grant(expires_at=(T0 - timedelta(days=1)).isoformat())])
    assert mode(pe) is Mode.M1
    pe, _ = engine(tmp_path / "pin", auto_cfg("M3"), key, [grant()], pinned="0" * 64)
    assert mode(pe) is Mode.M1 and "pinned fingerprint" in pe.grants.status
    pe, _ = engine(tmp_path / "pin2", auto_cfg("M3"), key, [grant()], pinned=signing.fingerprint(key.public_key()))
    assert mode(pe) is Mode.M3


def test_a_grant_cannot_name_a_mode_outside_m2_m3(tmp_path, key):
    pe, _ = engine(tmp_path, auto_cfg("M3"), key, [grant(mode="M1")])
    assert mode(pe) is Mode.M1 and "malformed grant" in pe.grants.status


def test_the_policy_engine_has_no_way_to_raise_a_mode():
    public = {n for n in dir(PolicyEngine) if not n.startswith("_")}
    assert public == {"resolve", "downgrade", "clear_downgrade", "downgrades", "halted", "may_deploy_outside_gate"}
    assert {n for n in dir(GrantStore) if not n.startswith("_")} == {"reload", "restore", "max_mode"}


# ---- broker capabilities ----------------------------------------------------------------------------------------------
def test_prorealtime_ticket_adapter_supports_m1_at_most(tmp_path, key):
    pe, _ = engine(tmp_path, auto_cfg("M3"), key, [grant()], adapter=PROREALTIME_TICKET)
    r = pe.resolve(decision(), ctx())
    assert r.mode is Mode.M1 and "supports at most M1" in r.reasons[-1]


def test_live_proorder_scripts_need_an_effective_m3_grant(tmp_path, key):
    pe, _ = engine(tmp_path, auto_cfg("M3"), key, [grant(mode="M2")], adapter=PROORDER_LIVE_SCRIPT)
    r = pe.resolve(decision(), ctx())
    assert r.mode is Mode.M0 and "outside the gate" in r.reasons[-1]  # the gate only observes and reconciles
    assert not pe.may_deploy_outside_gate("s1", T0)[0]
    pe3, _ = engine(tmp_path / "m3", auto_cfg("M3"), key, [grant(mode="M3")], adapter=PROORDER_LIVE_SCRIPT)
    assert pe3.may_deploy_outside_gate("s1", T0)[0]
    assert not pe3.may_deploy_outside_gate("s2", T0)[0]


# ---- every M2 condition must hold, otherwise M1 -------------------------------------------------------------------------
@pytest.mark.parametrize("change, reason", [
    (dict(notional=600.0), "above the auto limit"),
    (dict(d=decision(confidence=0.4)), "confidence is below"),
    (dict(d=decision(confidence=None)), "confidence is below"),
    (dict(now=T0.replace(hour=23, minute=30)), "outside trading hours"),
    (dict(now=T0 + timedelta(days=5)), "outside trading hours"),     # a Saturday
    (dict(now=T0.replace(hour=14)), "inside event blackout"),
    (dict(risk_passed=False), "risk gate did not pass"),
    (dict(fresh=False), "data is not fresh"),
    (dict(reconciled=False), "broker is not reconciled"),
])
def test_m2_conditions(tmp_path, key, change, reason):
    cfg = make_cfg()
    cfg["policy"]["rules"] = [{"name": "auto", "match": {"strategy": "*"}, "mode": "M2"}]
    cfg["policy"]["auto"].update(auto_limit_notional=500, confidence_threshold=0.6,
                                 trading_hours={"timezone": "UTC", "weekdays": [0, 1, 2, 3, 4], "windows": ["08:00-22:00"]},
                                 event_blackouts=[{"start": T0.replace(hour=13).isoformat(), "end": T0.replace(hour=15).isoformat(),
                                                   "label": "rate decision"}])
    pe, _ = engine(tmp_path, cfg, key, [grant(mode="M2")])
    assert pe.resolve(decision(), ctx(notional=400.0)).mode is Mode.M2
    d = change.pop("d", decision())
    change.setdefault("notional", 400.0)
    r = pe.resolve(d, ctx(**change))
    assert r.mode is Mode.M1 and reason in r.reasons[-1]


def test_veto_window_is_reported_only_for_m2(tmp_path, key):
    cfg = auto_cfg("M2", policy__auto__veto_window_seconds=120)
    pe, _ = engine(tmp_path, cfg, key, [grant(mode="M2")])
    assert pe.resolve(decision(), ctx()).veto_window_seconds == 120
    cfg1 = make_cfg(policy__auto__veto_window_seconds=120)
    pe1, _ = engine(tmp_path / "m1", cfg1)
    assert pe1.resolve(decision(), ctx()).veto_window_seconds == 0
