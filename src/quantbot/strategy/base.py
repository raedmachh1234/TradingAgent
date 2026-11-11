"""Strategy interface: signal, sizing, exits.

A strategy sees a read-only context and returns Decisions. It never sees a broker, the executor, the
risk gate or the real account. The position it reads is its own model position (what it would hold if
every decision had been executed), which is what makes its decisions identical in every execution mode.
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Mapping

from ..core.types import Bar, Decision, Instrument, Intent, OrderType, Side


@dataclass(frozen=True)
class Signal:
    direction: int                      # +1 long, -1 short, 0 flat
    confidence: float | None = None     # 0..1, or None when there is no calibrated number
    expected_value: float | None = None # net of costs, account currency, or None when unknown
    regime: str = "unknown"
    features: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class ExitPlan:
    stop_price: float | None = None
    target_price: float | None = None


class StrategyContext:
    """Read-only view handed to a strategy on every bar."""

    __slots__ = ("now", "capital", "allow_short", "_bars", "_position", "_instruments")

    def __init__(self, now: datetime, capital: float, allow_short: bool, bars_fn: Callable[[str, int | None], list[Bar]],
                 position_fn: Callable[[str], float], instruments: Mapping[str, Instrument]) -> None:
        self.now, self.capital, self.allow_short = now, capital, allow_short
        self._bars, self._position, self._instruments = bars_fn, position_fn, instruments

    def bars(self, symbol: str, n: int | None = None) -> list[Bar]:
        return self._bars(symbol, n)

    def closes(self, symbol: str, n: int | None = None) -> list[float]:
        return [b.close for b in self._bars(symbol, n)]

    def position(self, symbol: str) -> float:
        """The strategy's own model position, not the broker's."""
        return self._position(symbol)

    def instrument(self, symbol: str) -> Instrument:
        return self._instruments[symbol]


class Strategy(ABC):
    """A sub-bot. Subclasses implement signal(), size() and exits(); on_bar() composes them."""

    def __init__(self, strategy_id: str, version: str, symbols: list[str], params: Mapping[str, float] | None = None) -> None:
        self.id, self.version, self.symbols = strategy_id, version, list(symbols)
        self.params = dict(params or {})

    @abstractmethod
    def signal(self, ctx: StrategyContext, symbol: str) -> Signal | None: ...

    @abstractmethod
    def size(self, ctx: StrategyContext, symbol: str, signal: Signal, price: float) -> float: ...

    @abstractmethod
    def exits(self, ctx: StrategyContext, symbol: str, signal: Signal, price: float) -> ExitPlan: ...

    def on_bar(self, ctx: StrategyContext) -> list[Decision]:
        out: list[Decision] = []
        for symbol in self.symbols:
            last = ctx.bars(symbol, 1)
            if not last:
                continue
            price = last[-1].close
            sig = self.signal(ctx, symbol)
            if sig is None:
                continue
            pos = ctx.position(symbol)
            common = dict(strategy_id=self.id, strategy_version=self.version, symbol=symbol, ts=ctx.now, reference_price=price,
                          order_type=OrderType.MARKET, confidence=sig.confidence, expected_value=sig.expected_value,
                          regime=sig.regime, features=tuple(sorted((k, float(v)) for k, v in sig.features.items())))
            if pos == 0 and sig.direction != 0:
                if sig.direction < 0 and not ctx.allow_short:
                    continue
                inst = ctx.instrument(symbol)
                qty = math.floor(self.size(ctx, symbol, sig, price) / inst.qty_step + 1e-9) * inst.qty_step
                if qty < inst.min_qty:
                    continue
                plan = self.exits(ctx, symbol, sig, price)
                out.append(Decision(side=Side.BUY if sig.direction > 0 else Side.SELL, intent=Intent.ENTRY, quantity=qty,
                                    stop_price=plan.stop_price, target_price=plan.target_price, **common))
            elif pos != 0 and (sig.direction == 0 or sig.direction * pos < 0):
                out.append(Decision(side=Side.SELL if pos > 0 else Side.BUY, intent=Intent.EXIT, quantity=abs(pos), **common))
        return out
