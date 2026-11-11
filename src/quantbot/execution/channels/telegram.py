"""Telegram channel: a push message with Approve and Reject buttons.

Each button carries a code bound to one proposal, one order fingerprint and one action. A press counts only
if it comes from an allow-listed user and the code matches (see TelegramAuthenticator). Edits are not
accepted here; they go through the CLI. The bot token is read from the environment, never from the repo.

Status: unit-tested against a fake Bot API. It has not yet been run against Telegram itself.
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime
from typing import Any, Callable

from ...core.types import UTC
from ..approval import HumanDecision, TelegramAuthenticator
from ..proposal import Proposal

Transport = Callable[[str, dict[str, Any]], dict[str, Any]]


def http_transport(token: str, timeout: float = 30.0) -> Transport:
    def call(method: str, params: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}", data=json.dumps(params).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed https host)
            return json.loads(resp.read().decode("utf-8"))
    return call


class TelegramChannel:
    name = "telegram"

    def __init__(self, authenticator: TelegramAuthenticator, chat_id: str | int, transport: Transport | None = None,
                 now: Callable[[], datetime] | None = None) -> None:
        if transport is None:
            token = os.environ.get("TELEGRAM_BOT_TOKEN")
            if not token:
                raise RuntimeError("TELEGRAM_BOT_TOKEN is not set (put it in .env, never in the repository)")
            transport = http_transport(token)
        self.auth, self.chat_id, self._call = authenticator, str(chat_id), transport
        self._now = now or (lambda: datetime.now(UTC))
        self._offset = 0
        self._fingerprints: dict[str, str] = {}

    def notify(self, proposal: Proposal) -> None:
        pid, fp = proposal.id, proposal.order.fingerprint
        self._fingerprints[pid] = fp
        buttons = [[{"text": "Approve", "callback_data": f"a:{pid}:{self.auth.code(pid, fp, 'approve')}"},
                    {"text": "Reject", "callback_data": f"r:{pid}:{self.auth.code(pid, fp, 'reject')}"}]]
        self._call("sendMessage", {"chat_id": self.chat_id, "text": proposal.render(), "reply_markup": {"inline_keyboard": buttons}})

    def poll(self) -> list[HumanDecision]:
        out: list[HumanDecision] = []
        resp = self._call("getUpdates", {"offset": self._offset, "timeout": 0, "allowed_updates": ["callback_query"]})
        for upd in resp.get("result", []):
            self._offset = max(self._offset, int(upd.get("update_id", 0)) + 1)
            cq = upd.get("callback_query")
            if not cq:
                continue  # plain messages are ignored: text can never approve anything
            parts = str(cq.get("data", "")).split(":")
            if len(parts) != 3 or parts[0] not in ("a", "r"):
                continue
            action = "approve" if parts[0] == "a" else "reject"
            pid, code = parts[1], parts[2]
            sender = str(cq.get("from", {}).get("id", ""))
            out.append(HumanDecision(pid, self._fingerprints.get(pid, ""), action, self._now(), self.name, sender, code,
                                     reason="rejected on Telegram" if action == "reject" else ""))
            try:
                self._call("answerCallbackQuery", {"callback_query_id": cq.get("id"), "text": f"{action} received"})
            except Exception:
                pass
        return out
