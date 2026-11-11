"""The risk gate: always on, in every mode, and the only way an order can reach the executor.

The gate issues a verdict bound to one exact order (by fingerprint) and signed with a secret that only the
gate holds. The executor refuses any order that does not come with a valid, fresh, passing verdict, so
strategy code cannot bypass the gate even if it somehow obtained a reference to the executor.

Entries and exits are treated differently, as in day-trader-skill's risk check: getting out must always be
possible, so for an order that only reduces a position most limits become warnings rather than blocks.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Any, Mapping

from ..core.types import Instrument, Intent, Order, OrderType, Side
from .killswitch import KillSwitch


@dataclass(frozen=True)
class RiskLimits:
    require_stop_on_entry: bool
    allow_short: bool
    blocked_symbols: tuple[str, ...]
    min_order_notional: float
    max_order_notional: float
    max_risk_per_trade_pct: float
    max_position_pct: float
    max_gross_exposure_pct: float
    max_open_positions: int
    daily_loss_limit_pct: float
    max_drawdown_pct: float
    max_orders_per_minute: int
    max_orders_per_day: int
    max_data_age_seconds: float
    kill_switch_allows_exits: bool
    strategy_max_capital_use_pct: float
    strategy_max_open_positions: int

    @classmethod
    def from_config(cls, risk: Mapping[str, Any]) -> "RiskLimits":
        flat = {k: v for k, v in risk.items() if k != "per_strategy"}
        flat["blocked_symbols"] = tuple(flat["blocked_symbols"])
        flat["strategy_max_capital_use_pct"] = risk["per_strategy"]["max_capital_use_pct"]
        flat["strategy_max_open_positions"] = risk["per_strategy"]["max_open_positions"]
        unknown = set(flat) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f"unknown risk settings: {sorted(unknown)}")
        return cls(**flat)


@dataclass(frozen=True)
class RiskSnapshot:
    """Everything the gate needs to know, captured at one instant."""

    now: datetime
    equity: float
    cash: float
    day_pnl: float
    drawdown_pct: float
    price: float | None
    data_age_seconds: float | None
    instrument: Instrument | None
    strategy_position: float
    strategy_capital: float
    strategy_exposure: float          # gross notional of the sub-bot, pending proposals included
    gross_exposure: float             # whole account, pending proposals included
    position_notional: float          # this instrument, whole account, pending proposals included
    open_positions: int
    strategy_open_positions: int
    recent_order_times: tuple[datetime, ...] = ()
    orders_today: int = 0
    active_fingerprints: frozenset[str] = frozenset()
    reconciled: bool = True
    halted: bool = False
    data_ok: bool = True


@dataclass(frozen=True)
class RiskCheck:
    name: str
    passed: bool
    blocking: bool
    detail: str = ""


@dataclass(frozen=True)
class RiskVerdict:
    fingerprint: str
    passed: bool
    checks: tuple[RiskCheck, ...]
    ts: datetime
    notional: float
    worst_case_loss: float
    worst_case_loss_pct: float
    token: str

    def blocks(self) -> list[str]:
        return [f"{c.name}: {c.detail}" for c in self.checks if not c.passed and c.blocking]

    def warnings(self) -> list[str]:
        return [f"{c.name}: {c.detail}" for c in self.checks if not c.passed and not c.blocking]


class RiskGate:
    def __init__(self, limits: RiskLimits, kill_switch: KillSwitch) -> None:
        self.limits = limits
        self.kill_switch = kill_switch
        self.__secret = os.urandom(32)

    def _token(self, fingerprint: str, passed: bool, ts: datetime) -> str:
        msg = f"{fingerprint}|{int(passed)}|{ts.isoformat()}".encode("utf-8")
        return hmac.new(self.__secret, msg, hashlib.sha256).hexdigest()

    def verify(self, verdict: RiskVerdict, order: Order, now: datetime, max_age_seconds: float) -> tuple[bool, str]:
        """Called by the executor: is this a genuine, passing, fresh verdict for exactly this order?"""
        if not isinstance(verdict, RiskVerdict):
            return False, "no risk verdict"
        if not hmac.compare_digest(verdict.token, self._token(verdict.fingerprint, verdict.passed, verdict.ts)):
            return False, "risk verdict was not issued by the risk gate"
        if not verdict.passed:
            return False, "risk verdict is a block"
        if verdict.fingerprint != order.fingerprint:
            return False, "risk verdict is for a different order"
        if (now - verdict.ts).total_seconds() > max_age_seconds:
            return False, "risk verdict is stale"
        return True, "ok"

    def check(self, order: Order, s: RiskSnapshot) -> RiskVerdict:
        L = self.limits
        exit_only = order.intent is Intent.EXIT
        checks: list[RiskCheck] = []

        def add(name: str, ok: bool, detail: str = "", hard: bool = False) -> None:
            # Soft rules block entries and only warn on exits; hard rules block everything.
            checks.append(RiskCheck(name, bool(ok), hard or not exit_only, "" if ok else detail))

        inst = s.instrument
        price = order.limit_price if order.order_type is OrderType.LIMIT and order.limit_price else s.price
        ks = self.kill_switch.engaged
        add("kill_switch", not ks or (exit_only and L.kill_switch_allows_exits), "kill switch is engaged", hard=True)
        add("instrument", inst is not None and price is not None and price > 0, "unknown instrument or no price", hard=True)
        if inst is None or price is None or price <= 0:
            return self._verdict(order, checks, s.now, 0.0, 0.0, s.equity)
        steps = order.quantity / inst.qty_step
        add("quantity", order.quantity >= inst.min_qty and abs(steps - round(steps)) < 1e-6,
            f"quantity {order.quantity:g} is below the minimum or off the step {inst.qty_step:g}", hard=True)
        add("duplicate", order.fingerprint not in s.active_fingerprints, "an identical order is already pending", hard=True)
        notional = order.quantity * price * inst.multiplier
        add("halt", not s.halted, "trading is halted by a downgrade trigger")  # blocks entries, warns on exits
        if exit_only:
            reduces = s.strategy_position * order.side.sign < 0 and order.quantity <= abs(s.strategy_position) + 1e-9
            add("exit_reduces", reduces, f"exit of {order.quantity:g} does not fit the position {s.strategy_position:g}", hard=True)
            worst = 0.0
        else:
            add("blocked_symbol", order.symbol not in L.blocked_symbols, f"{order.symbol} is on the blocked list")
            add("short", order.side is Side.BUY or L.allow_short, "short selling is not enabled")
            has_stop = order.stop_price is not None
            add("stop_required", has_stop or not L.require_stop_on_entry, "an entry needs a stop")
            if has_stop:
                right_side = order.stop_price < price if order.side is Side.BUY else order.stop_price > price
                add("stop_side", right_side, f"stop {order.stop_price:g} is on the wrong side of {price:g}")
                worst = order.quantity * abs(price - order.stop_price) * inst.multiplier
            else:
                worst = notional
            add("risk_per_trade", worst <= L.max_risk_per_trade_pct / 100.0 * s.equity + 1e-9,
                f"worst-case loss {worst:.2f} exceeds {L.max_risk_per_trade_pct:g}% of equity")
            add("min_notional", notional >= L.min_order_notional, f"notional {notional:.2f} is below {L.min_order_notional:g}")
            add("max_notional", notional <= L.max_order_notional, f"notional {notional:.2f} exceeds {L.max_order_notional:g}")
            add("position_size", s.position_notional + notional <= L.max_position_pct / 100.0 * s.equity + 1e-9,
                f"position would exceed {L.max_position_pct:g}% of equity")
            add("gross_exposure", s.gross_exposure + notional <= L.max_gross_exposure_pct / 100.0 * s.equity + 1e-9,
                f"gross exposure would exceed {L.max_gross_exposure_pct:g}% of equity")
            add("open_positions", s.open_positions < L.max_open_positions or s.strategy_position != 0,
                f"already {s.open_positions} open positions")
            add("strategy_capital", s.strategy_exposure + notional <= L.strategy_max_capital_use_pct / 100.0 * s.strategy_capital + 1e-9,
                "the sub-bot would exceed its allocated capital")
            add("strategy_open_positions", s.strategy_open_positions < L.strategy_max_open_positions or s.strategy_position != 0,
                f"the sub-bot already has {s.strategy_open_positions} open positions")
            add("cash", order.side is Side.SELL or notional * inst.margin_rate <= s.cash + 1e-9, "not enough cash")
        add("daily_loss", s.day_pnl > -L.daily_loss_limit_pct / 100.0 * (s.equity - s.day_pnl),
            f"daily loss limit of {L.daily_loss_limit_pct:g}% is hit")
        add("drawdown", s.drawdown_pct < L.max_drawdown_pct, f"drawdown {s.drawdown_pct:.2f}% breaches {L.max_drawdown_pct:g}%")
        fresh = s.data_ok and s.data_age_seconds is not None and s.data_age_seconds <= L.max_data_age_seconds
        add("data_fresh", fresh, "market data is stale or failed quality checks")
        add("reconciled", s.reconciled, "broker and internal positions disagree")
        recent = sum(1 for t in s.recent_order_times if (s.now - t).total_seconds() < 60.0)
        add("order_rate", recent < L.max_orders_per_minute, f"more than {L.max_orders_per_minute} orders in a minute", hard=True)
        add("orders_per_day", s.orders_today < L.max_orders_per_day, f"more than {L.max_orders_per_day} orders today", hard=True)
        return self._verdict(order, checks, s.now, notional, worst, s.equity)

    def _verdict(self, order: Order, checks: list[RiskCheck], now: datetime, notional: float, worst: float, equity: float) -> RiskVerdict:
        passed = all(c.passed or not c.blocking for c in checks)
        pct = 0.0 if equity <= 0 else worst / equity * 100.0
        return RiskVerdict(order.fingerprint, passed, tuple(checks), now, notional, worst, pct,
                           self._token(order.fingerprint, passed, now))
