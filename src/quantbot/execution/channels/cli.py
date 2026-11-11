"""CLI channel: proposals are printed; decisions are signed with the operator key and queued."""
from __future__ import annotations

from typing import Callable

from ..approval import HumanDecision
from ..proposal import Proposal


class CliChannel:
    name = "cli"

    def __init__(self, out: Callable[[str], None] | None = None) -> None:
        self._out = out
        self._queue: list[HumanDecision] = []
        self.announced: list[str] = []

    def notify(self, proposal: Proposal) -> None:
        self.announced.append(proposal.id)
        if self._out:
            self._out(proposal.render())

    def submit(self, decision: HumanDecision) -> None:
        """Queue a decision. It still has to pass the operator-key authenticator to have any effect."""
        self._queue.append(decision)

    def poll(self) -> list[HumanDecision]:
        out, self._queue = self._queue, []
        return out
