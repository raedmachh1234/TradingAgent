from __future__ import annotations

from typing import Protocol

from ..approval import HumanDecision
from ..proposal import Proposal


class ApprovalChannel(Protocol):
    """A channel only transports. Whether a decision counts is decided by the authenticator of the same name."""

    name: str

    def notify(self, proposal: Proposal) -> None: ...

    def poll(self) -> list[HumanDecision]: ...
