"""Broker-versus-internal reconciliation, and the counterfactual record of vetoed proposals."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from ..core.types import Intent
from ..portfolio.ledger import Ledger
from .proposal import Proposal, State


@dataclass(frozen=True)
class Mismatch:
    symbol: str
    internal: float
    broker: float


class Reconciler:
    """Runs in every mode. A mismatch blocks new entries and fires the reconciliation downgrade."""

    def __init__(self, tolerance: float = 1e-9, sink: Callable[[str, Any], None] | None = None) -> None:
        self.tolerance = tolerance
        self.sink = sink or (lambda etype, payload: None)
        self.ok = True
        self.mismatches: list[Mismatch] = []

    def run(self, internal: Mapping[str, float], broker: Mapping[str, float]) -> bool:
        found = [Mismatch(s, internal.get(s, 0.0), broker.get(s, 0.0)) for s in sorted(set(internal) | set(broker))
                 if abs(internal.get(s, 0.0) - broker.get(s, 0.0)) > self.tolerance]
        ok = not found
        if ok != self.ok or found != self.mismatches:
            self.sink("RECONCILIATION", {"ok": ok, "mismatches": found})
        self.ok, self.mismatches = ok, found
        return ok


def veto_report(proposals: Mapping[str, Proposal], shadow: Ledger) -> dict[str, Any]:
    """What rejected and expired entries would have done, taken from the shadow book that filled every decision.

    value_of_vetoes > 0 means the operator's vetoes avoided losses; < 0 means they gave up gains.
    Open counterfactual positions are valued at the last price.
    """
    rows = []
    for p in proposals.values():
        if p.state not in (State.REJECTED, State.EXPIRED) or p.decision.intent is not Intent.ENTRY:
            continue
        tag = p.decision.decision_id
        closed = [t for t in shadow.trades if t.tag == tag]
        pnl = sum(t.pnl for t in closed)
        still_open = False
        for (_sid, sym), pos in shadow.positions.items():
            if pos.tag == tag and pos.qty:
                still_open = True
                pnl += (shadow.last_price.get(sym, pos.avg_price) - pos.avg_price) * pos.qty * shadow.instruments[sym].multiplier
        rows.append({"proposal": p.id, "state": p.state.value, "symbol": p.order.symbol, "reason": p.reject_reason,
                     "counterfactual_pnl": round(pnl, 2), "still_open": still_open})
    total = round(sum(r["counterfactual_pnl"] for r in rows), 2)
    return {"vetoed_or_expired": len(rows), "counterfactual_pnl": total, "value_of_vetoes": -total, "rows": rows}
