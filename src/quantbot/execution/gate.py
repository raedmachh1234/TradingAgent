"""ExecutionGate: the single path from a strategy's decision to anything that can become an order.

decision -> (cap exits to the real position) -> risk gate -> policy (mode) -> ApprovalService
The same code runs in backtest, paper, shadow and live. Only the mode and the broker adapter differ.
"""
from __future__ import annotations

from typing import Any, Mapping
from zoneinfo import ZoneInfo

from ..core.bus import EventBus
from ..core.clock import Clock
from ..core.types import UTC, Decision, Instrument, Intent, Mode, Order, digest
from ..data.service import History
from ..portfolio.ledger import Allocator, Ledger
from ..risk.gate import RiskGate, RiskSnapshot
from .approval import ApprovalService
from .executor import Executor
from .policy import PolicyContext, PolicyEngine
from .proposal import Proposal
from .reconcile import Reconciler


class ExecutionGate:
    def __init__(self, cfg: Mapping[str, Any], clock: Clock, bus: EventBus, ledger: Ledger, instruments: Mapping[str, Instrument],
                 allocator: Allocator, risk_gate: RiskGate, policy: PolicyEngine, approval: ApprovalService, executor: Executor,
                 history: History, reconciler: Reconciler, bad_symbols: set[str]) -> None:
        self.clock, self.bus, self.ledger, self.instruments, self.allocator = clock, bus, ledger, instruments, allocator
        self.risk, self.policy, self.approval, self.executor = risk_gate, policy, approval, executor
        self.history, self.reconciler, self.bad_symbols = history, reconciler, bad_symbols
        tz = cfg["account"]["day_timezone"]
        self._tz = UTC if str(tz).upper() == "UTC" else ZoneInfo(str(tz))
        self._seen: set[str] = set()
        approval.repropose = self._repropose
        approval.recheck_mode = self._recheck_mode

    def price(self, symbol: str) -> float | None:
        bar = self.history.last(symbol)
        return bar.close if bar else None

    def snapshot(self, order: Order, exclude: str | None = None) -> RiskSnapshot:
        now = self.clock.now()
        inst = self.instruments.get(order.symbol)
        bar = self.history.last(order.symbol)
        price = bar.close if bar else None
        pending = [p for p in self.approval.reserving(exclude) if p.order.intent is Intent.ENTRY]

        def claim(p: Proposal) -> float:
            px = self.price(p.order.symbol) or p.reference_price
            return max(0.0, p.order.quantity - p.filled_qty) * px * self.instruments[p.order.symbol].multiplier

        net = self.ledger.net_positions().get(order.symbol, 0.0)
        mult = inst.multiplier if inst else 1.0
        new_slots = {(p.order.strategy_id, p.order.symbol) for p in pending
                     if self.ledger.strategy_position(p.order.strategy_id, p.order.symbol) == 0}
        return RiskSnapshot(
            now=now, equity=self.ledger.equity, cash=self.ledger.cash, day_pnl=self.ledger.day_pnl,
            drawdown_pct=self.ledger.drawdown_pct, price=price,
            data_age_seconds=(now - bar.ts).total_seconds() if bar else None, instrument=inst,
            strategy_position=self.ledger.strategy_position(order.strategy_id, order.symbol),
            strategy_capital=self.allocator.capital_for(order.strategy_id),
            strategy_exposure=self.ledger.gross_exposure(order.strategy_id) + sum(claim(p) for p in pending if p.order.strategy_id == order.strategy_id),
            gross_exposure=self.ledger.gross_exposure() + sum(claim(p) for p in pending),
            position_notional=abs(net) * (price or 0.0) * mult + sum(claim(p) for p in pending if p.order.symbol == order.symbol),
            open_positions=self.ledger.open_positions() + len(new_slots),
            strategy_open_positions=self.ledger.open_positions(order.strategy_id) + sum(1 for s, _ in new_slots if s == order.strategy_id),
            recent_order_times=tuple(self.executor.order_times[-64:]),
            orders_today=self.executor.orders_on(now.astimezone(self._tz).date(), self._tz),
            active_fingerprints=frozenset(p.order.fingerprint for p in self.approval.reserving(exclude)),
            reconciled=self.reconciler.ok, halted=self.policy.halted, data_ok=order.symbol not in self.bad_symbols,
        )

    def on_decision(self, d: Decision) -> Proposal | None:
        if d.decision_id in self._seen:
            self.bus.audit("DECISION_DUPLICATE", {"decision": d.decision_id})
            return None
        self._seen.add(d.decision_id)
        return self._process(d, d.quantity, 0, None, d.reference_price)

    def _process(self, d: Decision, quantity: float, attempt: int, supersedes: str | None, reference_price: float) -> Proposal | None:
        def skip(why: str) -> None:
            self.bus.audit("DECISION_SKIPPED", {"decision": d.decision_id, "strategy": d.strategy_id, "symbol": d.symbol, "reason": why})

        actual = self.ledger.strategy_position(d.strategy_id, d.symbol)
        if d.intent is Intent.EXIT:
            # The strategy exits its model position; the order may only close what the account really holds.
            quantity = min(quantity, abs(actual)) if actual * d.side.sign < 0 else 0.0
            if quantity <= 0:
                skip("no real position to exit")
                return None
        else:
            if actual != 0:
                skip("the sub-bot already holds this instrument")
                return None
            if any(p.order.strategy_id == d.strategy_id and p.order.symbol == d.symbol and p.order.intent is Intent.ENTRY
                   for p in self.approval.reserving()):
                skip("an entry for this instrument is already pending")
                return None
        pid = "P-" + digest((d.decision_id, attempt))
        entry = d.intent is Intent.ENTRY
        order = Order(client_order_id="qb-" + pid[2:], symbol=d.symbol, side=d.side, quantity=quantity, order_type=d.order_type,
                      strategy_id=d.strategy_id, intent=d.intent, proposal_id=pid, limit_price=d.limit_price,
                      stop_price=d.stop_price if entry else None, target_price=d.target_price if entry else None)
        verdict = self.risk.check(order, self.snapshot(order))
        fresh = any(c.name == "data_fresh" and c.passed for c in verdict.checks)
        res = self.policy.resolve(d, PolicyContext(self.clock.now(), verdict.notional, verdict.passed, fresh, self.reconciler.ok))
        return self.approval.create(d, order, verdict, res, self.ledger.equity, reference_price, supersedes, attempt)

    def _recheck_mode(self, p: Proposal) -> Mode:
        verdict = self.risk.check(p.order, self.snapshot(p.order, p.id))
        fresh = any(c.name == "data_fresh" and c.passed for c in verdict.checks)
        ctx = PolicyContext(self.clock.now(), verdict.notional, verdict.passed, fresh, self.reconciler.ok)
        return self.policy.resolve(p.decision, ctx).mode

    def _repropose(self, old: Proposal) -> None:
        price = self.price(old.order.symbol)
        if price is None:
            return
        self.bus.audit("REPROPOSE", {"from": old.id, "reason": old.note, "new_reference_price": price})
        self._process(old.decision, old.order.quantity, old.attempt + 1, old.id, price)
