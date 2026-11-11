"""Random entry: the null baseline every real strategy will have to beat (e-book chapter 4).

Seeded, so the same seed gives the same entries in every run and every execution mode.
"""
from __future__ import annotations

import random
import zlib

from ..strategy.base import ExitPlan, Signal, Strategy, StrategyContext
from ..strategy.registry import register


@register("random_entry")
class RandomEntry(Strategy):
    def __init__(self, strategy_id, version, symbols, params=None) -> None:
        super().__init__(strategy_id, version, symbols, params)
        seed = int(self.params.get("seed", 11))
        self._rng = {s: random.Random(seed * 1_000_003 + zlib.crc32(f"{strategy_id}:{s}".encode())) for s in self.symbols}
        self._held: dict[str, int] = {s: 0 for s in self.symbols}

    def signal(self, ctx: StrategyContext, symbol: str) -> Signal | None:
        draw = self._rng[symbol].random()  # exactly one draw per bar and symbol, whatever the position
        if ctx.position(symbol) != 0:
            self._held[symbol] += 1
            keep = self._held[symbol] < int(self.params.get("hold_bars", 5))
            return Signal(1 if keep else 0, confidence=0.5, regime="normal", features={"held_bars": self._held[symbol]})
        self._held[symbol] = 0
        enter = draw < float(self.params.get("entry_probability", 0.1))
        return Signal(1 if enter else 0, confidence=0.5, regime="normal", features={"draw": round(draw, 6)})

    def size(self, ctx: StrategyContext, symbol: str, signal: Signal, price: float) -> float:
        inst = ctx.instrument(symbol)
        return ctx.capital * float(self.params.get("notional_pct", 10.0)) / 100.0 / (price * inst.multiplier)

    def exits(self, ctx: StrategyContext, symbol: str, signal: Signal, price: float) -> ExitPlan:
        tick = ctx.instrument(symbol).tick_size
        stop = price * (1 - float(self.params.get("stop_pct", 3.0)) / 100.0)
        return ExitPlan(stop_price=round(round(stop / tick) * tick, 10), target_price=None)
