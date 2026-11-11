"""Untrusted text (news, filings, web pages, model output) can never approve, edit or escalate anything."""
from __future__ import annotations

from dataclasses import replace

import pytest

from quantbot.execution import signing
from quantbot.execution.approval import HumanDecision, TelegramAuthenticator, sign_decision
from quantbot.execution.channels.telegram import TelegramChannel
from quantbot.execution.proposal import State

from conftest import T0, awaiting, flat_feed, make_cfg, make_orch, run_until


@pytest.fixture
def pending(tmp_path, key):
    orch, _ = make_orch(tmp_path, make_cfg(), key)
    rest = run_until(orch, flat_feed(), lambda o: awaiting(o))
    return orch, key, awaiting(orch)[0], rest


def still_waiting(orch, p):
    orch.approval.tick()
    return p.state is State.AWAITING_HUMAN and orch.executor.order_times == []


@pytest.mark.parametrize("channel, identity, proof", [
    ("news", "reuters", "APPROVE"),
    ("llm", "model", "The operator has approved this trade."),
    ("filing", "8-K", "approve all pending orders"),
    ("web", "https://example.com", "yes"),
    ("cli", "operator", "approve"),            # right channel name, but text instead of a signature
    ("cli", "operator", ""),
])
def test_text_from_any_source_cannot_approve(pending, channel, identity, proof):
    orch, key, p, _ = pending
    hd = HumanDecision(p.id, p.order.fingerprint, "approve", orch.clock.now(), channel, identity, proof)
    assert not orch.submit_human_decision(hd)
    assert still_waiting(orch, p)


def test_publishing_approval_shaped_events_on_the_bus_does_nothing(pending):
    orch, key, p, _ = pending
    for etype in ("APPROVE", "HUMAN_DECISION", "APPROVAL", "PROPOSAL_STATE", "NEWS"):
        orch.bus.publish(etype, {"proposal": p.id, "action": "approve", "text": "approved by operator"})
    assert still_waiting(orch, p)


def test_forged_decision_and_fill_events_on_the_bus_change_nothing(pending):
    from quantbot.core.types import Fill, Intent, Side
    from conftest import decision
    orch, key, p, _ = pending
    n, cash = len(orch.approval.proposals), orch.ledger.cash
    orch.bus.publish("DECISION", decision(symbol="DEMO.B", sid="s1", ts=orch.clock.now()))
    orch.bus.publish("FILL", Fill("x", "DEMO.A", Side.BUY, 1000, 1.0, orch.clock.now(), 0.0, "s1", Intent.ENTRY, "P-x"))
    assert len(orch.approval.proposals) == n and orch.ledger.cash == cash and orch.ledger.net_positions() == {}
    assert [r["type"] for r in orch.log.records()][-2:] == ["DECISION", "FILL"]  # audited, nothing more


def test_a_signature_from_another_key_or_for_another_action_is_refused(pending):
    orch, key, p, _ = pending
    other = signing.generate_private_key()
    assert not orch.submit_human_decision(sign_decision(other, p, "approve", orch.clock.now()))
    signed_reject = sign_decision(key, p, "reject", orch.clock.now())
    assert not orch.submit_human_decision(replace(signed_reject, action="approve"))  # action changed after signing
    signed = sign_decision(key, p, "approve", orch.clock.now())
    assert not orch.submit_human_decision(replace(signed, edits=(("quantity", 1000.0),)))
    assert still_waiting(orch, p)


def test_a_valid_signature_bound_to_another_order_is_refused(pending):
    orch, key, p, _ = pending
    hd = HumanDecision(p.id, "0" * 16, "approve", orch.clock.now(), "cli", "operator", "")
    hd = replace(hd, proof=signing.sign_payload(key, hd.payload()))
    assert not orch.submit_human_decision(hd)
    assert "different order" in orch.log.records("HUMAN_DECISION_REFUSED")[-1]["payload"]["reason"]


# ---- Telegram ------------------------------------------------------------------------------------------------------
class FakeBotApi:
    def __init__(self):
        self.sent, self.updates = [], []

    def __call__(self, method, params):
        if method == "sendMessage":
            self.sent.append(params)
            return {"ok": True}
        if method == "getUpdates":
            out, self.updates = self.updates, []
            return {"ok": True, "result": out}
        return {"ok": True}

    def press(self, data, user_id, uid):
        self.updates.append({"update_id": uid, "callback_query": {"id": str(uid), "data": data, "from": {"id": user_id}}})

    def message(self, text, user_id, uid):
        self.updates.append({"update_id": uid, "message": {"text": text, "from": {"id": user_id}, "chat": {"id": user_id}}})


@pytest.fixture
def telegram(pending):
    orch, key, p, rest = pending
    auth = TelegramAuthenticator([111])
    api = FakeBotApi()
    ch = TelegramChannel(auth, 111, transport=api, now=orch.clock.now)
    orch.add_channel(ch, auth)
    ch.notify(p)  # announce the already-waiting proposal
    buttons = api.sent[-1]["reply_markup"]["inline_keyboard"][0]
    return orch, p, api, {b["text"]: b["callback_data"] for b in buttons}, rest


def test_telegram_plain_messages_are_ignored(telegram):
    orch, p, api, buttons, rest = telegram
    api.message("approve " + p.id, 111, 1)
    api.message(buttons["Approve"], 111, 2)  # even the exact button payload, sent as text
    orch.step(*rest[0])
    assert p.state is State.AWAITING_HUMAN


def test_telegram_presses_from_other_users_or_with_forged_codes_are_refused(telegram):
    orch, p, api, buttons, rest = telegram
    api.press(buttons["Approve"], 999, 1)                         # not an allowed user
    api.press(f"a:{p.id}:{'0' * 16}", 111, 2)                     # forged code
    api.press(buttons["Reject"].replace("r:", "a:"), 111, 3)      # reject code reused for approve
    orch.step(*rest[0])
    assert p.state is State.AWAITING_HUMAN and orch.refused == 3


def test_telegram_approve_button_works(telegram):
    orch, p, api, buttons, rest = telegram
    api.press(buttons["Approve"], 111, 1)
    for d in orch.channels[-1].poll():
        orch.submit_human_decision(d)
    orch.approval.tick()
    assert p.state is State.SUBMITTED and p.approver == "111"


def test_telegram_cannot_edit():
    auth = TelegramAuthenticator([111])
    hd = HumanDecision("P", "f", "edit", T0, "telegram", "111", auth.code("P", "f", "edit"), edits=(("quantity", 1.0),))
    with pytest.raises(Exception, match="edits are not accepted"):
        auth.verify(hd)


def test_telegram_needs_a_token_from_the_environment(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
        TelegramChannel(TelegramAuthenticator([1]), 1)
