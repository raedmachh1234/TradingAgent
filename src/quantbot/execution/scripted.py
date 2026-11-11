"""A scripted operator for replays, tests and the demo.

It holds a private key and signs each decision exactly as the command-line tool does, so the decisions it
produces go through the same authentication as a real operator's. It is never part of a live configuration.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable

from .approval import HumanDecision, sign_decision
from .proposal import Proposal, State

Rule = Callable[[Proposal], tuple[str, dict[str, Any]]]


def approve_all(p: Proposal) -> tuple[str, dict[str, Any]]:
    return "approve", {}


def reject_all(p: Proposal) -> tuple[str, dict[str, Any]]:
    return "reject", {"reason": "scripted rejection"}


class ScriptedHuman:
    """Decides on each awaiting proposal `delay_steps` bars after first seeing it (0 = at once), by `rule`.

    A rule may return ("ignore", {}) to leave a proposal unanswered until it expires.
    """

    def __init__(self, private_key, rule: Rule = approve_all, delay_steps: int = 0, identity: str = "operator") -> None:
        self.key, self.rule, self.delay, self.identity = private_key, rule, delay_steps, identity
        self._first_seen: dict[str, int] = {}

    def __call__(self, orch) -> Iterable[HumanDecision]:
        out: list[HumanDecision] = []
        for p in orch.approval.awaiting():
            if p.state is not State.AWAITING_HUMAN:
                continue
            if orch.steps - self._first_seen.setdefault(p.id, orch.steps) < self.delay:
                continue
            action, kw = self.rule(p)
            if action == "ignore":
                continue
            out.append(sign_decision(self.key, p, action, orch.clock.now(), identity=self.identity, **kw))
        return out
