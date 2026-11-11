"""ApprovalService: creates proposals, takes authenticated human decisions, expires, revalidates, submits.

A decision changes a proposal only if an authenticator registered for its channel vouches for it. Nothing in
this module reads free text looking for an approval: text from news, filings, web pages or a model is data,
and there is no code path from data to a state change.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Callable, Mapping, Protocol

from ..core.bus import EventBus
from ..core.clock import Clock
from ..core.types import Decision, Fill, Instrument, Intent, Mode, Order, OrderType, Side
from ..risk.gate import RiskGate, RiskSnapshot, RiskVerdict
from . import signing
from .executor import ExecutionFailed, ExecutionRefused, Executor
from .policy import ModeResolution
from .proposal import RESERVING, Proposal, State


class AuthError(Exception):
    pass


class DecisionRefused(Exception):
    pass


@dataclass(frozen=True)
class HumanDecision:
    proposal_id: str
    fingerprint: str
    action: str                 # approve | reject | edit
    decided_at: datetime
    channel: str
    identity: str
    proof: str
    reason: str = ""
    edits: tuple[tuple[str, float], ...] = ()

    def payload(self) -> dict[str, Any]:
        return {"proposal_id": self.proposal_id, "fingerprint": self.fingerprint, "action": self.action,
                "decided_at": self.decided_at, "identity": self.identity, "reason": self.reason, "edits": dict(self.edits)}


class Authenticator(Protocol):
    name: str

    def verify(self, decision: HumanDecision) -> None: ...


class OperatorKeyAuthenticator:
    """Decisions signed with the operator's Ed25519 key (the CLI channel)."""

    def __init__(self, public_key, name: str = "cli") -> None:
        self.public_key, self.name = public_key, name

    def verify(self, decision: HumanDecision) -> None:
        if not signing.verify_payload(self.public_key, decision.payload(), decision.proof):
            raise AuthError("signature does not verify against the operator key")


def sign_decision(private_key, proposal: Proposal, action: str, decided_at: datetime, reason: str = "",
                  edits: Mapping[str, float] | None = None, identity: str = "operator", channel: str = "cli") -> HumanDecision:
    """Used by the command-line tool, where the operator's private key is available."""
    hd = HumanDecision(proposal.id, proposal.order.fingerprint, action, decided_at, channel, identity, "", reason,
                       tuple(sorted((edits or {}).items())))
    return replace(hd, proof=signing.sign_payload(private_key, hd.payload()))


class TelegramAuthenticator:
    """Button presses from allow-listed Telegram users, each carrying a code bound to one proposal and one action."""

    name = "telegram"

    def __init__(self, allowed_user_ids, secret: bytes | None = None) -> None:
        self.allowed = {str(c) for c in allowed_user_ids}
        self._secret = secret or os.urandom(32)

    def code(self, proposal_id: str, fingerprint: str, action: str) -> str:
        return hmac.new(self._secret, f"{proposal_id}|{fingerprint}|{action}".encode(), hashlib.sha256).hexdigest()[:16]

    def verify(self, decision: HumanDecision) -> None:
        if decision.action not in ("approve", "reject"):
            raise AuthError("edits are not accepted on this channel")
        if str(decision.identity) not in self.allowed:
            raise AuthError("sender is not an allowed Telegram user")
        if not hmac.compare_digest(decision.proof, self.code(decision.proposal_id, decision.fingerprint, decision.action)):
            raise AuthError("code does not match this proposal")


class ApprovalService:
    def __init__(self, cfg: Mapping[str, Any], clock: Clock, bus: EventBus, risk_gate: RiskGate, executor: Executor,
                 instruments: Mapping[str, Instrument], snapshot_fn: Callable[[Order, str | None], RiskSnapshot],
                 price_fn: Callable[[str], float | None]) -> None:
        ex = cfg["execution"]
        self.ttl = timedelta(seconds=float(ex["proposal_ttl_seconds"]))
        self.drift_bps = float(ex["price_drift_tolerance_bps"])
        self.max_reproposals = int(ex["max_reproposals"])
        self.bounds = dict(ex["edit_bounds"])
        self.currency = cfg["account"]["currency"]
        self.clock, self.bus, self.risk, self.executor = clock, bus, risk_gate, executor
        self.instruments, self._snapshot, self._price = instruments, snapshot_fn, price_fn
        self.proposals: dict[str, Proposal] = {}
        self._by_order: dict[str, str] = {}
        self._auth: dict[str, Authenticator] = {}
        self._notify: list[Callable[[Proposal], None]] = []
        self.repropose: Callable[[Proposal], None] | None = None
        self.recheck_mode: Callable[[Proposal], Mode] | None = None  # set by the gate: the mode the policy gives now

    # ---- wiring ----------------------------------------------------------------------------------
    def register_authenticator(self, auth: Authenticator) -> None:
        self._auth[auth.name] = auth

    def add_notifier(self, fn: Callable[[Proposal], None]) -> None:
        self._notify.append(fn)

    def _state(self, p: Proposal, new: State, note: str = "") -> None:
        p.move(new, self.clock.now(), note)
        self.bus.audit("PROPOSAL_STATE", {"proposal": p.id, "state": new, "note": note})

    # ---- creation --------------------------------------------------------------------------------
    def create(self, decision: Decision, order: Order, verdict: RiskVerdict, res: ModeResolution, equity: float,
               reference_price: float, supersedes: str | None = None, attempt: int = 0) -> Proposal:
        now = self.clock.now()
        p = Proposal(order.proposal_id, decision, order, res.mode, res.reasons, verdict, now, now + self.ttl, reference_price,
                     equity, self.currency, supersedes=supersedes, attempt=attempt)
        self.proposals[p.id] = p
        self._by_order[order.client_order_id] = p.id
        self.bus.audit("PROPOSAL_CREATED", {"proposal": p.id, "decision": decision.decision_id, "order": order, "mode": res.mode,
                                            "mode_reasons": res.reasons, "risk_passed": verdict.passed, "risk_blocks": verdict.blocks(),
                                            "risk_warnings": verdict.warnings(), "worst_case_loss": verdict.worst_case_loss,
                                            "expires_at": p.expires_at, "supersedes": supersedes})
        if not verdict.passed:
            self._state(p, State.RISK_BLOCKED, "; ".join(verdict.blocks()))
            return p
        self._state(p, State.RISK_PASSED)
        if res.mode is Mode.M0:
            self._state(p, State.OBSERVED, "observe only")
        elif res.mode is Mode.M1:
            self._state(p, State.AWAITING_HUMAN)
            self._announce(p)
        elif res.mode is Mode.M2 and res.veto_window_seconds > 0:
            p.execute_after = now + timedelta(seconds=res.veto_window_seconds)
            self._state(p, State.AWAITING_VETO, f"executes at {p.execute_after.isoformat()} unless vetoed")
            self._announce(p)
        else:
            p.approver, p.decided_at = f"policy:{res.mode.name}", now
            self._state(p, State.APPROVED, "automatic")
        return p

    def _announce(self, p: Proposal) -> None:
        for fn in self._notify:
            try:
                fn(p)
            except Exception as exc:  # a broken notifier must not break the gate
                self.bus.audit("NOTIFY_FAILED", {"proposal": p.id, "error": str(exc)})

    # ---- human decisions -------------------------------------------------------------------------
    def decide(self, hd: HumanDecision) -> Proposal:
        now = self.clock.now()

        def refuse(why: str) -> None:
            self.bus.audit("HUMAN_DECISION_REFUSED", {"proposal": hd.proposal_id, "action": hd.action, "channel": hd.channel,
                                                      "identity": hd.identity, "reason": why})
            raise DecisionRefused(why)

        auth = self._auth.get(hd.channel)
        if auth is None:
            refuse(f"no authenticated channel named {hd.channel!r}")
        try:
            auth.verify(hd)
        except AuthError as exc:
            refuse(f"authentication failed: {exc}")
        p = self.proposals.get(hd.proposal_id)
        if p is None:
            refuse("unknown proposal")
        if hd.fingerprint != p.order.fingerprint and p.state in (State.AWAITING_HUMAN, State.AWAITING_VETO):
            refuse("decision is for a different order than the one proposed")
        if p.state is State.AWAITING_HUMAN and now >= p.expires_at:
            self._state(p, State.EXPIRED, "ttl")
            refuse("proposal has expired")
        if p.state not in (State.AWAITING_HUMAN, State.AWAITING_VETO):
            accepted = (State.APPROVED, State.EDITED, State.REVALIDATED, State.SUBMITTED, State.PARTIAL, State.FILLED)
            if hd.action == "approve" and p.approver == hd.identity and p.state in accepted:
                self.bus.audit("HUMAN_DECISION_DUPLICATE", {"proposal": p.id, "identity": hd.identity})
                return p  # the same approval delivered twice changes nothing
            refuse(f"proposal is {p.state.value}, not awaiting a decision")
        if p.state is State.AWAITING_VETO and hd.action != "reject":
            refuse("only a veto is possible during the veto window")
        if hd.action == "approve":
            p.approver, p.decided_at = hd.identity, now
            self._state(p, State.APPROVED, f"by {hd.identity} via {hd.channel}")
        elif hd.action == "reject":
            p.approver, p.decided_at, p.reject_reason = hd.identity, now, hd.reason
            self._state(p, State.REJECTED, hd.reason or "no reason given")
        elif hd.action == "edit":
            try:
                new_order = self._bounded_edit(p, dict(hd.edits))
            except DecisionRefused as exc:
                refuse(str(exc))
            p.approver, p.decided_at, p.edits, p.order = hd.identity, now, dict(hd.edits), new_order
            self._state(p, State.EDITED, f"by {hd.identity}: {dict(hd.edits)}")
        else:
            refuse(f"unknown action {hd.action!r}")
        self.bus.audit("HUMAN_DECISION", {"proposal": p.id, "action": hd.action, "identity": hd.identity, "channel": hd.channel,
                                          "reason": hd.reason, "edits": dict(hd.edits), "decision": p.decision.decision_id})
        return p

    def _bounded_edit(self, p: Proposal, edits: dict[str, float]) -> Order:
        o, inst = p.order, self.instruments[p.order.symbol]
        unknown = set(edits) - {"quantity", "stop_price", "target_price", "limit_price"}
        if unknown or not edits:
            raise DecisionRefused(f"edit refused: unsupported fields {sorted(unknown)}" if unknown else "edit refused: nothing to change")
        qty = float(edits.get("quantity", o.quantity))
        steps = qty / inst.qty_step
        if qty > o.quantity + 1e-12:
            raise DecisionRefused("edit refused: size can go down, never up")
        if qty < inst.min_qty or abs(steps - round(steps)) > 1e-6:
            raise DecisionRefused("edit refused: quantity is below the minimum or off the step")
        stop, target, limit = o.stop_price, o.target_price, o.limit_price
        long = o.side is Side.BUY
        if o.intent is Intent.EXIT and set(edits) - {"quantity"}:
            raise DecisionRefused("edit refused: only the size of an exit can be edited")
        if "stop_price" in edits:
            stop = float(edits["stop_price"])
            ref = p.reference_price
            tighter = o.stop_price is None or (stop >= o.stop_price if long else stop <= o.stop_price)
            right_side = stop < ref if long else stop > ref
            if not (tighter and right_side):
                raise DecisionRefused("edit refused: a stop can only move closer to the entry")
        if "target_price" in edits:
            target = float(edits["target_price"])
            if not (target > p.reference_price if long else target < p.reference_price):
                raise DecisionRefused("edit refused: the target must stay on the profit side")
        if "limit_price" in edits:
            limit = float(edits["limit_price"])
            if o.order_type is not OrderType.LIMIT or o.limit_price is None:
                raise DecisionRefused("edit refused: this is not a limit order")
            if abs(limit / o.limit_price - 1) * 1e4 > float(self.bounds["limit_price_bps"]):
                raise DecisionRefused("edit refused: limit price moved too far")
        return replace(o, quantity=qty, stop_price=stop, target_price=target, limit_price=limit)

    # ---- time-driven work ------------------------------------------------------------------------
    def tick(self) -> None:
        """Expire, close veto windows, then revalidate and submit whatever is approved."""
        now = self.clock.now()
        for p in list(self.proposals.values()):
            if p.state is State.AWAITING_HUMAN and now >= p.expires_at:
                self._state(p, State.EXPIRED, "ttl")
            elif p.state is State.AWAITING_VETO and p.execute_after is not None and now >= p.execute_after:
                mode_now = self.recheck_mode(p) if self.recheck_mode else p.mode
                if mode_now < Mode.M2:  # the M2 conditions stopped holding during the window
                    self._state(p, State.CANCELLED, f"M2 conditions no longer hold ({mode_now.name}); re-proposed")
                    if self.repropose is not None:
                        self.repropose(p)
                    continue
                p.approver, p.decided_at = "policy:M2", now
                self._state(p, State.APPROVED, "veto window passed")
        for p in list(self.proposals.values()):
            if p.state in (State.APPROVED, State.EDITED):
                self._revalidate_and_submit(p)

    def _revalidate_and_submit(self, p: Proposal) -> None:
        price = self._price(p.order.symbol)
        problems: list[str] = []
        if price is None:
            problems.append("no current price")
        else:
            drift = abs(price / p.reference_price - 1.0) * 1e4
            if drift > self.drift_bps:
                problems.append(f"price drift {drift:.1f} bps exceeds {self.drift_bps:g} bps")
        verdict = self.risk.check(p.order, self._snapshot(p.order, p.id))
        if not verdict.passed:
            problems.append("risk gate: " + "; ".join(verdict.blocks()))
        if problems:
            self._state(p, State.CANCELLED, "revalidation failed: " + "; ".join(problems))
            if p.attempt < self.max_reproposals and self.repropose is not None:
                self.repropose(p)
            return
        p.verdict = verdict
        self._state(p, State.REVALIDATED)
        try:
            ack = self.executor.submit(p.order, verdict)
        except (ExecutionRefused, ExecutionFailed) as exc:
            self._state(p, State.FAILED, str(exc))
            return
        if ack.accepted:
            self._state(p, State.SUBMITTED, "duplicate suppressed" if ack.duplicate else "")
        else:
            self._state(p, State.FAILED, ack.message)

    # ---- broker events ---------------------------------------------------------------------------
    def on_fill(self, fill: Fill) -> None:
        p = self.proposals.get(self._by_order.get(fill.client_order_id, ""))
        if p is None or p.state not in (State.SUBMITTED, State.PARTIAL):
            return
        total = p.filled_qty + fill.quantity
        p.avg_fill_price = (p.avg_fill_price * p.filled_qty + fill.price * fill.quantity) / total
        p.filled_qty = total
        done = total >= p.order.quantity - 1e-9
        self._state(p, State.FILLED if done else State.PARTIAL, f"{total:g} of {p.order.quantity:g} at {p.avg_fill_price:.4f}")

    def on_broker_cancel(self, client_order_id: str) -> None:
        p = self.proposals.get(self._by_order.get(client_order_id, ""))
        if p is not None and p.state in (State.SUBMITTED, State.PARTIAL):
            self._state(p, State.CANCELLED, "cancelled at the broker")

    # ---- views -----------------------------------------------------------------------------------
    def awaiting(self) -> list[Proposal]:
        return [p for p in self.proposals.values() if p.state in (State.AWAITING_HUMAN, State.AWAITING_VETO)]

    def reserving(self, exclude: str | None = None) -> list[Proposal]:
        return [p for p in self.proposals.values() if p.state in RESERVING and p.id != exclude]

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for p in self.proposals.values():
            out[p.state.value] = out.get(p.state.value, 0) + 1
        return dict(sorted(out.items()))
