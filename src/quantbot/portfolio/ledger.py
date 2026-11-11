"""Internal book: positions per sub-bot and instrument, cash, equity, daily P&L and drawdown.

Two instances exist at run time. The actual ledger is fed by fills from the executor and is what the risk
gate and reconciliation read. The shadow ledger is fed by a second paper broker that fills every decision,
whatever the execution mode; it is what strategies read, and it gives the counterfactual for vetoed trades.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping
from zoneinfo import ZoneInfo

from ..core.types import UTC, Fill, Instrument


@dataclass
class Position:
    qty: float = 0.0
    avg_price: float = 0.0
    tag: str = ""                  # proposal or decision id of the opening fill
    opened_at: datetime | None = None
    fees: float = 0.0              # opening commissions not yet charged to a closed trade


@dataclass(frozen=True)
class Trade:
    """A closed (or partly closed) round trip."""

    strategy_id: str
    symbol: str
    tag: str
    qty: float
    entry_price: float
    exit_price: float
    opened_at: datetime | None
    closed_at: datetime
    pnl: float                     # after the opening and closing commissions of this quantity
    exit_kind: str


class Ledger:
    def __init__(self, starting_cash: float, instruments: Mapping[str, Instrument], day_timezone: str = "UTC") -> None:
        self.instruments = dict(instruments)
        self.cash = float(starting_cash)
        self.starting_cash = float(starting_cash)
        self.positions: dict[tuple[str, str], Position] = {}
        self.last_price: dict[str, float] = {}
        self.realized: dict[str, float] = {}
        self.fees = 0.0
        self.trades: list[Trade] = []
        self._tz = UTC if day_timezone.upper() == "UTC" else ZoneInfo(day_timezone)
        self._day: object | None = None
        self.day_start_equity = float(starting_cash)
        self.high_water = float(starting_cash)

    # ---- updates -------------------------------------------------------------------------------
    def on_fill(self, fill: Fill) -> None:
        inst = self.instruments[fill.symbol]
        key = (fill.strategy_id, fill.symbol)
        pos = self.positions.setdefault(key, Position())
        signed = fill.side.sign * fill.quantity
        self.cash -= signed * fill.price * inst.multiplier + fill.commission
        self.fees += fill.commission
        self.last_price.setdefault(fill.symbol, fill.price)
        if pos.qty == 0 or pos.qty * signed > 0:  # opening or adding
            total = pos.qty + signed
            pos.avg_price = (pos.avg_price * abs(pos.qty) + fill.price * abs(signed)) / abs(total)
            if pos.qty == 0:
                pos.tag, pos.opened_at = fill.proposal_id, fill.ts
            pos.qty = total
            pos.fees += fill.commission
            return
        closing = min(abs(signed), abs(pos.qty))
        direction = 1 if pos.qty > 0 else -1
        entry_fees = pos.fees * closing / abs(pos.qty)
        pos.fees -= entry_fees
        pnl = direction * (fill.price - pos.avg_price) * closing * inst.multiplier - fill.commission - entry_fees
        self.realized[fill.strategy_id] = self.realized.get(fill.strategy_id, 0.0) + pnl
        self.trades.append(Trade(fill.strategy_id, fill.symbol, pos.tag, closing, pos.avg_price, fill.price,
                                 pos.opened_at, fill.ts, pnl, fill.kind if fill.kind != "order" else fill.intent.value.lower()))
        remainder = abs(signed) - closing
        pos.qty -= direction * closing
        if abs(pos.qty) < 1e-12:
            pos.qty, pos.avg_price, pos.tag, pos.opened_at, pos.fees = 0.0, 0.0, "", None, 0.0
        if remainder > 1e-12:  # the fill flipped the position
            pos.qty, pos.avg_price, pos.tag, pos.opened_at = fill.side.sign * remainder, fill.price, fill.proposal_id, fill.ts

    def roll_day(self, ts: datetime) -> None:
        """Call once at the start of every step, before that step's fills: a new day starts from the last close."""
        day = ts.astimezone(self._tz).date()
        if self._day is None:
            self._day = day
        elif day != self._day:
            self._day, self.day_start_equity = day, self.equity

    def mark(self, symbol: str, price: float) -> None:
        self.last_price[symbol] = price

    def close_step(self) -> None:
        """Call once after every symbol of a step is marked."""
        self.high_water = max(self.high_water, self.equity)

    # ---- views ---------------------------------------------------------------------------------
    def _value(self, symbol: str, qty: float) -> float:
        return qty * self.last_price.get(symbol, 0.0) * self.instruments[symbol].multiplier

    @property
    def equity(self) -> float:
        return self.cash + sum(self._value(sym, p.qty) for (_, sym), p in self.positions.items())

    @property
    def day_pnl(self) -> float:
        return self.equity - self.day_start_equity

    @property
    def drawdown_pct(self) -> float:
        return 0.0 if self.high_water <= 0 else max(0.0, (1 - self.equity / self.high_water) * 100.0)

    def strategy_position(self, strategy_id: str, symbol: str) -> float:
        p = self.positions.get((strategy_id, symbol))
        return p.qty if p else 0.0

    def net_positions(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for (_, sym), p in self.positions.items():
            if p.qty:
                out[sym] = out.get(sym, 0.0) + p.qty
        return {s: q for s, q in out.items() if abs(q) > 1e-12}

    def gross_exposure(self, strategy_id: str | None = None) -> float:
        return sum(abs(self._value(sym, p.qty)) for (sid, sym), p in self.positions.items()
                   if strategy_id is None or sid == strategy_id)

    def open_positions(self, strategy_id: str | None = None) -> int:
        return sum(1 for (sid, _), p in self.positions.items() if p.qty and (strategy_id is None or sid == strategy_id))


class Allocator:
    """Splits the account's capital between sub-bots by fixed weights.

    The allocation handed to strategies is a fixed share of the configured capital, not of live equity, so
    that sizing (and therefore every decision) does not depend on which trades were actually executed.
    Covariance-aware allocation over sub-bot P&L streams arrives with the foundation modules.
    """

    def __init__(self, capital: float, weights: Mapping[str, float]) -> None:
        total = sum(weights.values())
        if total <= 0:
            raise ValueError("allocator needs at least one positive weight")
        self.capital = float(capital)
        self.shares = {k: v / total for k, v in weights.items()}

    def capital_for(self, strategy_id: str) -> float:
        return self.capital * self.shares.get(strategy_id, 0.0)
