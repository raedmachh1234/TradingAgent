"""Paper broker: a deterministic bar-driven simulator. No network, no credentials.

Conventions (chosen to avoid look-ahead):
- An order submitted while bar k is being processed can fill no earlier than the open of bar k+1.
- Market orders fill at that open, plus half the spread and slippage against the order.
- Limit orders fill when the bar trades through the limit, at the limit or at the open if the open is better.
- A filled entry with a stop or target gets a protective bracket held by the broker. If a bar touches both,
  the stop is assumed to have come first. A bar that opens beyond the stop fills at the open (gap risk).
- Orders are idempotent on client_order_id: a repeated submission returns the first acknowledgement.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Mapping

from ..core.types import Bar, Fill, Instrument, Intent, Mode, Order, OrderType, Side
from .base import BrokerAdapter, BrokerCapabilities, BrokerError, OrderAck


@dataclass
class _Working:
    order: Order
    remaining: float


@dataclass
class _Bracket:
    order: Order      # the entry order it protects
    qty: float


class PaperBroker(BrokerAdapter):
    def __init__(self, instruments: Mapping[str, Instrument], spread_bps: float = 2.0, slippage_bps: float = 1.0,
                 commission_bps: float = 1.0, min_commission: float = 0.0, max_participation: float | None = None,
                 name: str = "paper") -> None:
        self.capabilities = BrokerCapabilities(name, frozenset(Mode), is_paper=True)
        self.instruments = dict(instruments)
        self.spread_bps, self.slippage_bps = float(spread_bps), float(slippage_bps)
        self.commission_bps, self.min_commission = float(commission_bps), float(min_commission)
        self.max_participation = max_participation
        self._working: dict[str, _Working] = {}
        self._acks: dict[str, OrderAck] = {}
        self._brackets: list[_Bracket] = []
        self._positions: dict[str, float] = {}
        self._fail_next = 0
        self._cancelled: list[str] = []
        self.accepted: list[Order] = []  # every order accepted, in order; a duplicate never appears twice

    # ---- adapter interface ---------------------------------------------------------------------
    def submit(self, order: Order) -> OrderAck:
        if order.client_order_id in self._acks:
            return replace(self._acks[order.client_order_id], duplicate=True)
        if self._fail_next > 0:
            self._fail_next -= 1
            raise BrokerError("simulated broker outage")
        if order.symbol not in self.instruments or order.quantity <= 0:
            ack = OrderAck(order.client_order_id, False, message="rejected: unknown instrument or non-positive quantity")
        else:
            self._working[order.client_order_id] = _Working(order, order.quantity)
            self.accepted.append(order)
            ack = OrderAck(order.client_order_id, True)
        self._acks[order.client_order_id] = ack
        return ack

    def cancel(self, client_order_id: str) -> bool:
        return self._working.pop(client_order_id, None) is not None

    def positions(self) -> dict[str, float]:
        return {s: q for s, q in self._positions.items() if abs(q) > 1e-12}

    def open_orders(self) -> list[Order]:
        return [w.order for w in self._working.values()]

    # ---- simulation ----------------------------------------------------------------------------
    def inject_failures(self, n: int) -> None:
        """Make the next n submissions raise BrokerError (tests and drills)."""
        self._fail_next = int(n)

    def tamper_position(self, symbol: str, qty: float) -> None:
        """Change the broker-side position behind the gate's back (reconciliation drills only)."""
        self._positions[symbol] = self._positions.get(symbol, 0.0) + qty

    def _against(self, price: float, side: Side) -> float:
        adj = (self.spread_bps / 2.0 + self.slippage_bps) / 1e4
        return price * (1 + adj) if side is Side.BUY else price * (1 - adj)

    def _fill(self, order: Order, side: Side, qty: float, price: float, expected: float, bar: Bar, intent: Intent, kind: str) -> Fill:
        inst = self.instruments[order.symbol]
        commission = max(self.min_commission, qty * price * inst.multiplier * self.commission_bps / 1e4)
        self._positions[order.symbol] = self._positions.get(order.symbol, 0.0) + side.sign * qty
        coid = order.client_order_id if kind == "order" else f"{order.client_order_id}:{kind}"
        return Fill(coid, order.symbol, side, qty, price, bar.ts, commission, order.strategy_id, intent, order.proposal_id,
                    kind=kind, expected_price=expected)

    def drain_cancelled(self) -> list[str]:
        """Client order ids the broker cancelled itself since the last call."""
        out, self._cancelled = self._cancelled, []
        return out

    def _cancel_working_exits(self, strategy_id: str, symbol: str) -> None:
        # A protective stop or target just closed the position: a resting exit order must not sell it twice.
        for coid, w in list(self._working.items()):
            if w.order.intent is Intent.EXIT and w.order.strategy_id == strategy_id and w.order.symbol == symbol:
                del self._working[coid]
                self._cancelled.append(coid)

    def _reduce_brackets(self, strategy_id: str, symbol: str, qty: float) -> None:
        for b in list(self._brackets):
            if qty <= 1e-12:
                break
            if b.order.strategy_id == strategy_id and b.order.symbol == symbol:
                take = min(b.qty, qty)
                b.qty -= take
                qty -= take
                if b.qty <= 1e-12:
                    self._brackets.remove(b)

    def on_bar(self, bar: Bar) -> list[Fill]:
        fills: list[Fill] = []
        inst = self.instruments.get(bar.symbol)
        if inst is None:
            return fills
        budget = None if self.max_participation is None else bar.volume * self.max_participation
        for coid, w in list(self._working.items()):
            o = w.order
            if o.symbol != bar.symbol:
                continue
            if o.order_type is OrderType.MARKET:
                raw = bar.open
            elif o.side is Side.BUY and bar.low <= o.limit_price:
                raw = min(o.limit_price, bar.open)
            elif o.side is Side.SELL and bar.high >= o.limit_price:
                raw = max(o.limit_price, bar.open)
            else:
                continue
            qty = w.remaining
            if budget is not None:
                qty = min(qty, math.floor(budget / inst.qty_step + 1e-9) * inst.qty_step)
                if qty <= 0:
                    continue
                budget -= qty
            price = self._against(raw, o.side) if o.order_type is OrderType.MARKET else raw
            fills.append(self._fill(o, o.side, qty, price, raw, bar, o.intent, "order"))
            w.remaining -= qty
            if w.remaining <= 1e-12:
                del self._working[coid]
            if o.intent is Intent.ENTRY and (o.stop_price is not None or o.target_price is not None):
                self._brackets.append(_Bracket(o, qty))
            elif o.intent is Intent.EXIT:
                self._reduce_brackets(o.strategy_id, o.symbol, qty)
        for b in list(self._brackets):
            o = b.order
            if o.symbol != bar.symbol:
                continue
            long = o.side is Side.BUY
            out = o.side.opposite
            if o.stop_price is not None and (bar.low <= o.stop_price if long else bar.high >= o.stop_price):
                raw = min(o.stop_price, bar.open) if long else max(o.stop_price, bar.open)
                fills.append(self._fill(o, out, b.qty, self._against(raw, out), raw, bar, Intent.EXIT, "stop"))
                self._brackets.remove(b)
                self._cancel_working_exits(o.strategy_id, o.symbol)
            elif o.target_price is not None and (bar.high >= o.target_price if long else bar.low <= o.target_price):
                raw = max(o.target_price, bar.open) if long else min(o.target_price, bar.open)
                fills.append(self._fill(o, out, b.qty, raw, raw, bar, Intent.EXIT, "target"))
                self._brackets.remove(b)
                self._cancel_working_exits(o.strategy_id, o.symbol)
        return fills
