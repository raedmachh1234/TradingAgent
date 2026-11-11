"""Moving-average crossover: a toy sub-bot used to exercise the plumbing. No edge is claimed for it."""
from __future__ import annotations

import math

from ..strategy.base import ExitPlan, Signal, Strategy, StrategyContext
from ..strategy.registry import register


@register("ma_crossover")
class MACrossover(Strategy):
    """Long while the fast average is above the slow one; stop at a multiple of ATR; target at a multiple of the risk."""

    def _atr(self, ctx: StrategyContext, symbol: str) -> float | None:
        n = int(self.params.get("atr_window", 14))
        bars = ctx.bars(symbol, n + 1)
        if len(bars) < n + 1:
            return None
        trs = [max(b.high - b.low, abs(b.high - p.close), abs(b.low - p.close)) for p, b in zip(bars[:-1], bars[1:], strict=True)]
        return sum(trs) / len(trs)

    def signal(self, ctx: StrategyContext, symbol: str) -> Signal | None:
        fast, slow = int(self.params.get("fast", 10)), int(self.params.get("slow", 30))
        closes = ctx.closes(symbol, slow)
        atr = self._atr(ctx, symbol)
        if len(closes) < slow or atr is None or atr <= 0:
            return None
        f, s = sum(closes[-fast:]) / fast, sum(closes) / slow
        gap = (f - s) / s
        direction = 1 if f > s else (-1 if ctx.allow_short and f < s else 0)
        rets = [math.log(b / a) for a, b in zip(closes[:-1], closes[1:], strict=True)]
        recent, base = rets[-10:], rets
        vol = lambda xs: math.sqrt(sum(x * x for x in xs) / len(xs))
        regime = "high_vol" if vol(recent) > 1.5 * vol(base) else "normal"
        # An uncalibrated squashing of the gap, in ATR units. It is a display number until Phase 6 calibrates it.
        confidence = 1.0 / (1.0 + math.exp(-abs(gap) / (atr / closes[-1])))
        return Signal(direction, confidence=round(confidence, 6), expected_value=None, regime=regime,
                      features={"ma_gap": round(gap, 8), "atr": round(atr, 8), "fast": f, "slow": s})

    def size(self, ctx: StrategyContext, symbol: str, signal: Signal, price: float) -> float:
        atr = signal.features["atr"]
        stop_distance = float(self.params.get("stop_atr", 2.0)) * atr
        inst = ctx.instrument(symbol)
        risk_money = ctx.capital * float(self.params.get("risk_pct", 0.5)) / 100.0
        qty_by_risk = risk_money / (stop_distance * inst.multiplier)
        qty_by_notional = ctx.capital * float(self.params.get("max_notional_pct", 20.0)) / 100.0 / (price * inst.multiplier)
        return max(0.0, min(qty_by_risk, qty_by_notional))

    def exits(self, ctx: StrategyContext, symbol: str, signal: Signal, price: float) -> ExitPlan:
        distance = float(self.params.get("stop_atr", 2.0)) * signal.features["atr"]
        tick = ctx.instrument(symbol).tick_size
        rnd = lambda x: round(round(x / tick) * tick, 10)
        sign = 1 if signal.direction > 0 else -1
        return ExitPlan(stop_price=rnd(price - sign * distance),
                        target_price=rnd(price + sign * float(self.params.get("target_r", 2.0)) * distance))
