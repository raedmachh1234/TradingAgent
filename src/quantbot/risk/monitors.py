"""Downgrade triggers. Each one can only lower autonomy (to M1) or halt; none can raise it.

Triggers: kill switch, daily loss limit, drawdown breach, stale data, bad data, reconciliation mismatch,
repeated broker errors, abnormal slippage, model calibration decay.
"""
from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime
from typing import Any, Mapping, Sequence

from ..core.types import Fill
from ..portfolio.ledger import Ledger
from .gate import RiskLimits
from .killswitch import KillSwitch


class Monitors:
    def __init__(self, cfg: Mapping[str, Any], policy, kill_switch: KillSwitch, limits: RiskLimits) -> None:
        th = cfg["downgrade"]["thresholds"]
        self.policy, self.kill, self.limits = policy, kill_switch, limits
        self.err_count, self.err_window = int(th["broker_errors_count"]), float(th["broker_errors_window_seconds"])
        self.slip_bps, self.slip_min = float(th["slippage_bps"]), int(th["slippage_min_fills"])
        self.brier_excess = float(th["calibration_brier_excess"])
        self._slippage: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=50))
        self._calibration: dict[str, tuple[float, float]] = {}

    def record_fill(self, fill: Fill) -> None:
        """Adverse slippage of an order fill against the price it was expected at, in basis points."""
        if fill.kind == "order" and fill.expected_price:
            self._slippage[fill.strategy_id].append(fill.side.sign * (fill.price / fill.expected_price - 1.0) * 1e4)

    def record_calibration(self, strategy_id: str, live_brier: float, validation_brier: float) -> None:
        self._calibration[strategy_id] = (float(live_brier), float(validation_brier))

    def evaluate(self, now: datetime, ledger: Ledger, *, stale_symbols: Sequence[str] = (), bad_symbols: Sequence[str] = (),
                 reconciled: bool = True, broker_error_times: Sequence[datetime] = ()) -> list[str]:
        """Check every trigger and apply the configured action. Returns the triggers that changed state."""
        fired: list[str] = []

        def hit(trigger: str, detail: str, strategy_id: str | None = None) -> None:
            if self.policy.downgrade(trigger, detail, now, strategy_id):
                fired.append(trigger)

        if self.kill.engaged:
            hit("kill_switch", self.kill.reason() or "engaged")
        limit = self.limits.daily_loss_limit_pct / 100.0 * ledger.day_start_equity
        if ledger.day_pnl <= -limit:
            hit("daily_loss", f"day P&L {ledger.day_pnl:.2f} is beyond -{limit:.2f}")
        if ledger.drawdown_pct >= self.limits.max_drawdown_pct:
            hit("drawdown", f"drawdown {ledger.drawdown_pct:.2f}% reached {self.limits.max_drawdown_pct:g}%")
        if stale_symbols:
            hit("stale_data", "stale: " + ", ".join(sorted(stale_symbols)))
        if bad_symbols:
            hit("bad_data", "failed quality checks: " + ", ".join(sorted(bad_symbols)))
        if not reconciled:
            hit("reconciliation", "broker and internal positions disagree")
        recent = [t for t in broker_error_times if (now - t).total_seconds() <= self.err_window]
        if len(recent) >= self.err_count:
            hit("broker_errors", f"{len(recent)} broker errors in {self.err_window:g}s")
        for sid, xs in self._slippage.items():
            if len(xs) >= self.slip_min and sum(xs) / len(xs) > self.slip_bps:
                hit("slippage", f"mean adverse slippage {sum(xs)/len(xs):.1f} bps over {len(xs)} fills", sid)
        for sid, (live, val) in self._calibration.items():
            if live - val > self.brier_excess:
                hit("calibration", f"Brier score {live:.3f} against {val:.3f} in validation", sid)
        return fired
