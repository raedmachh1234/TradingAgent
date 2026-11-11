"""Shared helpers. Every test runs offline on constructed or seeded synthetic data, with packaged defaults only."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import pytest
import yaml

from quantbot.core.config import load_config
from quantbot.core.types import Bar, Decision, Intent, OrderType, Side
from quantbot.execution import signing
from quantbot.execution.approval import OperatorKeyAuthenticator, sign_decision
from quantbot.execution.channels.cli import CliChannel
from quantbot.orchestrator import Orchestrator
from quantbot.strategy.base import ExitPlan, Signal, Strategy, StrategyContext
from quantbot.strategy.registry import register

UTC = timezone.utc
T0 = datetime(2025, 1, 6, 21, 0, tzinfo=UTC)  # a Monday, at the daily bar's close time


# ---- data helpers -------------------------------------------------------------------------------------
def business_days(n: int, start: datetime = T0) -> list[datetime]:
    out, t = [], start
    while len(out) < n:
        if t.weekday() < 5:
            out.append(t)
        t += timedelta(days=1)
    return out


def make_bars(symbol: str, closes: list[float], start: datetime = T0, wick: float = 0.001, volume: float = 1e6) -> list[Bar]:
    bars, prev = [], closes[0]
    for t, c in zip(business_days(len(closes), start), closes, strict=True):
        o = prev
        bars.append(Bar(symbol, t, o, max(o, c) * (1 + wick), min(o, c) * (1 - wick), c, volume))
        prev = c
    return bars


def feed(*series: list[Bar]) -> list[tuple[datetime, dict[str, Bar]]]:
    by: dict[datetime, dict[str, Bar]] = {}
    for s in series:
        for b in s:
            by.setdefault(b.ts, {})[b.symbol] = b
    return [(t, by[t]) for t in sorted(by)]


def flat_feed(n: int = 20, price: float = 100.0, symbol: str = "DEMO.A") -> list[tuple[datetime, dict[str, Bar]]]:
    return feed(make_bars(symbol, [price] * n))


# ---- a fully scripted sub-bot ---------------------------------------------------------------------------
@register("test_schedule")
class ScheduleStrategy(Strategy):
    """Long (or short) from bar `enter_at` to bar `exit_at`, counting delivered bars. No hidden state."""

    def signal(self, ctx: StrategyContext, symbol: str) -> Signal | None:
        p, n = self.params, len(ctx.bars(symbol))
        on = p.get("enter_at", 3) <= n < p.get("exit_at", 10**9)
        conf = p.get("confidence", 0.9)
        return Signal(int(p.get("side", 1)) if on else 0, confidence=None if conf is None else float(conf),
                      regime=str(p.get("regime", "normal")), features={"n": float(n)})

    def size(self, ctx: StrategyContext, symbol: str, signal: Signal, price: float) -> float:
        return float(self.params.get("qty", 10))

    def exits(self, ctx: StrategyContext, symbol: str, signal: Signal, price: float) -> ExitPlan:
        sign = 1 if signal.direction > 0 else -1
        sp, tp = self.params.get("stop_pct", 2.0), self.params.get("target_pct")
        return ExitPlan(stop_price=round(price * (1 - sign * sp / 100), 2) if sp else None,
                        target_price=round(price * (1 + sign * tp / 100), 2) if tp else None)


def sched(sid: str = "s1", symbols: tuple[str, ...] = ("DEMO.A",), **params: Any) -> dict[str, Any]:
    base = {"enter_at": 3, "exit_at": 8, "qty": 10, "stop_pct": 2.0}
    base.update(params)
    return {"id": sid, "class": "test_schedule", "version": "1", "symbols": list(symbols), "weight": 1.0,
            "status": "candidate", "params": base}


# ---- configuration -------------------------------------------------------------------------------------
def set_path(cfg: dict, dotted: str, value: Any) -> None:
    node = cfg
    *parents, leaf = dotted.split(".")
    for part in parents:
        node = node[part]
    if leaf not in node:
        raise KeyError(dotted)
    node[leaf] = value


def make_cfg(strategies: list[dict] | None = None, **dotted: Any) -> dict:
    """Packaged defaults with overrides; keyword names use '__' for dots: risk__max_order_notional=100."""
    cfg = load_config(read_user_file=False)
    cfg["strategies"] = strategies if strategies is not None else [sched()]
    for k, v in dotted.items():
        set_path(cfg, k.replace("__", "."), v)
    return cfg


def auto_cfg(mode: str, strategies: list[dict] | None = None, **dotted: Any) -> dict:
    """Rules asking for `mode` on every strategy, with the M2 limits opened up (a grant is still required)."""
    cfg = make_cfg(strategies, **dotted)
    cfg["policy"]["rules"] = [{"name": "all", "match": {"strategy": "*"}, "mode": mode}]
    cfg["policy"]["auto"]["auto_limit_notional"] = 1e9
    cfg["policy"]["auto"]["confidence_threshold"] = 0.0
    return cfg


# ---- signed grants and the orchestrator -------------------------------------------------------------------
def grant(strategy: str = "s1", mode: str = "M3", signed_at: str = "2024-01-01T00:00:00+00:00", **extra: Any) -> dict:
    return {"strategy": strategy, "max_mode": mode, "signed_at": signed_at, **extra}


def write_grants(base: Path, key, grants: list[dict]) -> dict:
    (base / "config").mkdir(parents=True, exist_ok=True)
    doc = signing.sign_grants({"version": 1, "grants": grants}, key)
    (base / "config" / "autonomy.yaml").write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    signing.save_public_key(key.public_key(), base / "config" / "operator.pub")
    return doc


def make_orch(base: Path, cfg: dict, key=None, *, log: bool = False, start: datetime | None = None, **kw: Any):
    key = key or signing.generate_private_key()
    orch = Orchestrator(cfg, base_dir=base, event_log=(base / "events.jsonl") if log else None,
                        start=start or T0 - timedelta(days=3), **kw)
    orch.add_channel(CliChannel(), OperatorKeyAuthenticator(key.public_key()))
    return orch, key


def decide(orch, key, proposal, action: str = "approve", **kw: Any) -> bool:
    return orch.submit_human_decision(sign_decision(key, proposal, action, orch.clock.now(), **kw))


def run_until(orch, steps, cond: Callable[[Any], bool], human=None):
    """Step until cond(orch) holds; return the remaining steps."""
    for i, (ts, bars) in enumerate(steps):
        orch.step(ts, bars, human)
        if cond(orch):
            return steps[i + 1:]
    raise AssertionError("condition never met")


def awaiting(orch):
    return orch.approval.awaiting()


def decision(symbol: str = "DEMO.A", side: Side = Side.BUY, intent: Intent = Intent.ENTRY, qty: float = 10, price: float = 100.0,
             stop: float | None = 98.0, ts: datetime = T0, sid: str = "s1", confidence: float | None = 0.9,
             regime: str = "normal") -> Decision:
    return Decision(sid, "1", symbol, side, intent, qty, ts, price, OrderType.MARKET, None, stop, None, confidence, None, regime)


@pytest.fixture
def key():
    return signing.generate_private_key()
