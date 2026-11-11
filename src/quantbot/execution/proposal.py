"""Proposals and their state machine.

PROPOSED -> RISK_PASSED -> AWAITING_HUMAN -> APPROVED | REJECTED | EDITED | EXPIRED
         -> REVALIDATED -> SUBMITTED -> FILLED | PARTIAL | CANCELLED | FAILED

Three states are added to the owner's list so that every outcome has a name in the audit log:
RISK_BLOCKED (the gate said no), OBSERVED (M0: logged, nothing placed) and AWAITING_VETO (M2 veto window).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from ..core.types import Decision, Mode, Order
from ..risk.gate import RiskVerdict


class State(str, Enum):
    PROPOSED = "PROPOSED"
    RISK_BLOCKED = "RISK_BLOCKED"
    RISK_PASSED = "RISK_PASSED"
    OBSERVED = "OBSERVED"
    AWAITING_HUMAN = "AWAITING_HUMAN"
    AWAITING_VETO = "AWAITING_VETO"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EDITED = "EDITED"
    EXPIRED = "EXPIRED"
    REVALIDATED = "REVALIDATED"
    SUBMITTED = "SUBMITTED"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


S = State
TRANSITIONS: dict[State, frozenset[State]] = {
    S.PROPOSED: frozenset({S.RISK_PASSED, S.RISK_BLOCKED}),
    S.RISK_PASSED: frozenset({S.AWAITING_HUMAN, S.AWAITING_VETO, S.APPROVED, S.OBSERVED}),
    S.AWAITING_HUMAN: frozenset({S.APPROVED, S.REJECTED, S.EDITED, S.EXPIRED, S.CANCELLED}),
    S.AWAITING_VETO: frozenset({S.APPROVED, S.REJECTED, S.CANCELLED}),
    S.APPROVED: frozenset({S.REVALIDATED, S.CANCELLED}),
    S.EDITED: frozenset({S.REVALIDATED, S.CANCELLED}),
    S.REVALIDATED: frozenset({S.SUBMITTED, S.FAILED, S.CANCELLED}),
    S.SUBMITTED: frozenset({S.PARTIAL, S.FILLED, S.CANCELLED, S.FAILED}),
    S.PARTIAL: frozenset({S.PARTIAL, S.FILLED, S.CANCELLED}),
    S.RISK_BLOCKED: frozenset(), S.OBSERVED: frozenset(), S.REJECTED: frozenset(), S.EXPIRED: frozenset(),
    S.FILLED: frozenset(), S.CANCELLED: frozenset(), S.FAILED: frozenset(),
}
TERMINAL = frozenset(s for s, nxt in TRANSITIONS.items() if not nxt)
# States in which the order is still a claim on capital and must be counted by the risk gate.
RESERVING = frozenset({S.AWAITING_HUMAN, S.AWAITING_VETO, S.APPROVED, S.EDITED, S.REVALIDATED, S.SUBMITTED, S.PARTIAL})


class IllegalTransition(Exception):
    pass


@dataclass
class Proposal:
    id: str
    decision: Decision
    order: Order
    mode: Mode
    mode_reasons: tuple[str, ...]
    verdict: RiskVerdict
    created_at: datetime
    expires_at: datetime
    reference_price: float
    equity: float
    currency: str = "EUR"
    state: State = State.PROPOSED
    approver: str | None = None
    decided_at: datetime | None = None
    reject_reason: str = ""
    edits: dict | None = None
    supersedes: str | None = None
    attempt: int = 0
    execute_after: datetime | None = None   # end of an M2 veto window
    filled_qty: float = 0.0
    avg_fill_price: float = 0.0
    note: str = ""
    history: list[tuple[datetime, State, str]] = field(default_factory=list)

    def move(self, new: State, at: datetime, note: str = "") -> None:
        if new not in TRANSITIONS[self.state]:
            raise IllegalTransition(f"{self.id}: {self.state.value} -> {new.value} is not allowed")
        self.state, self.note = new, note
        self.history.append((at, new, note))

    @property
    def notional(self) -> float:
        return self.verdict.notional

    def render(self) -> str:
        """The text a human sees before deciding. ASCII only, so it prints on any console."""
        d, o, v = self.decision, self.order, self.verdict
        fmt = lambda x: "n/a" if x is None else f"{x:,.4f}".rstrip("0").rstrip(".")
        ev = "n/a (no validated edge yet)" if d.expected_value is None else f"{d.expected_value:,.2f} {self.currency}"
        conf = "n/a" if d.confidence is None else f"{d.confidence:.2f} (uncalibrated)"
        feats = ", ".join(f"{k}={val:.4g}" for k, val in d.features[:6]) or "none"
        lines = [
            f"PROPOSAL {self.id}  [{self.mode.name}]  state {self.state.value}",
            f"  {o.side.value} {fmt(o.quantity)} {o.symbol}  {o.order_type.value}  ({o.intent.value.lower()})",
            f"  entry ~{fmt(self.reference_price)}  stop {fmt(o.stop_price)}  target {fmt(o.target_price)}",
            f"  notional {v.notional:,.2f} {self.currency}; worst-case loss {v.worst_case_loss:,.2f} {self.currency}"
            f" = {v.worst_case_loss_pct:.2f}% of equity {self.equity:,.2f}",
            f"  expected value net of costs: {ev}",
            f"  strategy {d.strategy_id} v{d.strategy_version}; confidence {conf}; regime {d.regime}",
            f"  key features: {feats}",
            f"  risk gate: {'PASS' if v.passed else 'BLOCK'}"
            + ("" if not v.warnings() else "; warnings: " + "; ".join(v.warnings()))
            + ("" if not v.blocks() else "; blocks: " + "; ".join(v.blocks())),
            f"  mode: {'; '.join(self.mode_reasons) or 'default'}",
            f"  expires {self.expires_at:%Y-%m-%d %H:%M} UTC; fingerprint {o.fingerprint}",
        ]
        return "\n".join(lines)
