"""Orchestrator: wires sub-bots, the data feed, the execution gate and the executor, and runs them bar by bar.

Per bar, in this order: broker fills at the bar's open and intrabar stops; mark to market; reconcile;
downgrade monitors; authenticated human decisions; expiries and submissions; strategies decide at the close.
An order created at one bar's close can fill no earlier than the next bar's open.

Decisions and fills are applied by direct calls; the event bus audits them and informs observers but
cannot create an order or change a position.

Two books are kept. The actual book is what the broker really holds. The shadow book fills every decision
through an identical paper broker regardless of mode; strategies read their position from it, so the stream
of decisions is the same in M0, M1, M2 and M3, and it doubles as the counterfactual for vetoed trades.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .brokers.base import BrokerAdapter, BrokerCapabilities
from .brokers.paper import PaperBroker
from .core.bus import EventBus
from .core.clock import SimClock
from .core.config import instruments as load_instruments
from .core.eventlog import EventLog
from .core.types import Bar, Decision, Fill, Order
from .data.quality import is_stale
from .data.service import History
from .execution import signing
from .execution.approval import ApprovalService, DecisionRefused, HumanDecision
from .execution.executor import Executor
from .execution.gate import ExecutionGate
from .execution.policy import GrantStore, PolicyEngine
from .execution.reconcile import Reconciler, veto_report
from .portfolio.ledger import Allocator, Ledger
from .risk.gate import RiskGate, RiskLimits
from .risk.killswitch import KillSwitch
from .risk.monitors import Monitors
from .strategy.base import StrategyContext
from .strategy.registry import StrategyRegistry

Human = Callable[["Orchestrator"], Iterable[HumanDecision]]


@dataclass
class RunResult:
    steps: int
    decision_ids: list[str]
    decision_hash: str
    proposal_states: dict[str, int]
    orders_sent: int
    fills: int
    equity: float
    shadow_equity: float
    downgrades: dict[str, Any]
    refused_decisions: int
    vetoes: dict[str, Any] = field(default_factory=dict)


class Orchestrator:
    def __init__(self, cfg: Mapping[str, Any], *, base_dir: Path | str = ".", event_log: Path | str | None = None,
                 kill_file: Path | str | None = None, broker: BrokerAdapter | None = None,
                 adapter_capabilities: BrokerCapabilities | None = None, start: datetime | None = None) -> None:
        self.cfg = cfg
        base = Path(base_dir)
        self.clock = SimClock(start)
        self.log = EventLog(event_log)
        self.bus = EventBus(self.log, self.clock)
        self.instruments = load_instruments(cfg)
        capital, costs, auto = float(cfg["account"]["paper_capital"]), cfg["costs"], cfg["autonomy"]
        self.registry = StrategyRegistry.from_config(cfg["strategies"])
        self.allocator = Allocator(capital, {e.strategy.id: e.weight for e in self.registry.active()})
        self.ledger = Ledger(capital, self.instruments, cfg["account"]["day_timezone"])
        self.shadow_ledger = Ledger(capital, self.instruments, cfg["account"]["day_timezone"])
        self.shadow_broker = PaperBroker(self.instruments, name="shadow", **costs)
        self.broker_caps = adapter_capabilities or (broker.capabilities if broker else None)
        broker = broker or PaperBroker(self.instruments, **costs)
        self.kill = KillSwitch(kill_file)
        self.limits = RiskLimits.from_config(cfg["risk"])
        self.risk = RiskGate(self.limits, self.kill)
        self.executor = Executor(broker, self.risk, self.clock, self.bus, cfg["execution"]["verdict_max_age_seconds"])
        self.grants = GrantStore(base / auto["grants_file"], base / auto["operator_public_key"], auto["cooling_off_hours"],
                                 sink=self.bus.audit)
        self.grants.restore(self.log.records())
        self.grants.reload(self.clock.now())
        pub = base / auto["operator_public_key"]
        self.command_verifier = signing.CommandVerifier(signing.load_public_key(pub) if pub.exists() else None)
        for r in self.log.records("OPERATOR_COMMAND"):  # a command used before a restart stays used
            self.command_verifier._seen.add(r["payload"]["nonce"])
        self.policy = PolicyEngine(cfg, self.grants, self.broker_caps or broker.capabilities, sink=self.bus.audit)
        self.history = History()
        self.reconciler = Reconciler(float(cfg["execution"]["reconcile_tolerance"]), sink=self.bus.audit)
        self.bad_symbols: set[str] = set()
        self.approval = ApprovalService(cfg, self.clock, self.bus, self.risk, self.executor, self.instruments,
                                        snapshot_fn=lambda order, exclude: self.gate.snapshot(order, exclude),
                                        price_fn=lambda symbol: self.gate.price(symbol))
        self.gate = ExecutionGate(cfg, self.clock, self.bus, self.ledger, self.instruments, self.allocator, self.risk, self.policy,
                                  self.approval, self.executor, self.history, self.reconciler, self.bad_symbols)
        self.monitors = Monitors(cfg, self.policy, self.kill, self.limits)
        self.channels: list[Any] = []
        self.decisions: list[Decision] = []
        self.fills: list[Fill] = []
        self.refused = 0
        self.steps = 0
        self.bus.audit("SESSION_START", {"capital": capital, "currency": cfg["account"]["currency"], "strategies": self.registry.ids(),
                                         "adapter": self.policy.adapter.name, "default_mode": self.policy.default_mode,
                                         "grants": self.grants.status})

    # ---- command paths ---------------------------------------------------------------------------
    # Decisions and fills reach the gate and the books by direct calls, never through the bus. The bus audits
    # every event and informs observers, so a component that can publish events cannot create an order.
    def submit_decision(self, d: Decision) -> None:
        """Entry point for a sub-bot's decision (the strategy loop below is the only caller in the bot)."""
        self.bus.publish("DECISION", d)
        self._on_decision(d)

    def _on_decision(self, d: Decision) -> None:
        self.decisions.append(d)
        # The shadow book takes every decision as if it had been approved at once.
        self.shadow_broker.submit(Order("sh-" + d.decision_id, d.symbol, d.side, d.quantity, d.order_type, d.strategy_id,
                                        d.intent, d.decision_id, d.limit_price, d.stop_price, d.target_price))
        self.gate.on_decision(d)

    def _on_fill(self, fill: Fill) -> None:
        self.fills.append(fill)
        self.ledger.on_fill(fill)
        self.approval.on_fill(fill)
        self.monitors.record_fill(fill)

    def add_channel(self, channel: Any, authenticator: Any) -> None:
        self.channels.append(channel)
        self.approval.register_authenticator(authenticator)
        self.approval.add_notifier(channel.notify)

    def operator_command(self, cmd: signing.OperatorCommand) -> tuple[bool, str]:
        """Release the kill switch or clear downgrades. Only commands signed with the operator key work."""
        now = self.clock.now()
        if cmd.action == "release_kill_switch":
            ok, why = self.kill.release(cmd, self.command_verifier, now)
        elif cmd.action == "clear_downgrade":
            ok, why = self.policy.clear_downgrade(cmd, self.command_verifier, now)
        else:
            ok, why = False, f"unknown command {cmd.action!r}"
        self.bus.audit("OPERATOR_COMMAND", {"action": cmd.action, "scope": cmd.scope, "nonce": cmd.nonce, "ok": ok, "detail": why})
        return ok, why

    def submit_human_decision(self, hd: HumanDecision) -> bool:
        try:
            self.approval.decide(hd)
            return True
        except DecisionRefused:
            self.refused += 1
            return False

    # ---- the loop --------------------------------------------------------------------------------
    def step(self, ts: datetime, bars: Mapping[str, Bar], human: Human | None = None) -> None:
        self.clock.set(ts)
        self.ledger.roll_day(ts)
        self.shadow_ledger.roll_day(ts)
        for bar in bars.values():
            for fill in self.executor.on_bar(bar):
                self.bus.publish("FILL", fill)
                self._on_fill(fill)
            for coid in self.executor.drain_cancelled():
                self.approval.on_broker_cancel(coid)
            for fill in self.shadow_broker.on_bar(bar):
                self.shadow_ledger.on_fill(fill)
            self.history.append(bar)
            self.ledger.mark(bar.symbol, bar.close)
            self.shadow_ledger.mark(bar.symbol, bar.close)
        self.ledger.close_step()
        self.shadow_ledger.close_step()
        self._monitor(ts)
        self._take_human_decisions(human)
        self.approval.tick()
        for entry in self.registry.active():
            sid = entry.strategy.id
            ctx = StrategyContext(ts, self.allocator.capital_for(sid), self.limits.allow_short, self.history.bars,
                                  lambda symbol, sid=sid: self.shadow_ledger.strategy_position(sid, symbol), self.instruments)
            for d in entry.strategy.on_bar(ctx):
                self.submit_decision(d)
        self._take_human_decisions(human)  # an operator who answers at once: the order fills at the next open
        self.approval.tick()
        self._monitor(ts)                  # again after order activity, so errors in this bar count at once
        self.steps += 1

    def _monitor(self, ts: datetime) -> None:
        self.reconciler.run(self.ledger.net_positions(), self.executor.broker_positions())
        symbols = sorted({s for e in self.registry.active() for s in e.strategy.symbols})
        stale = [s for s in symbols if self.history.last(s) is not None
                 and is_stale(self.history.last(s).ts, ts, self.limits.max_data_age_seconds)]
        self.monitors.evaluate(ts, self.ledger, stale_symbols=stale, bad_symbols=sorted(self.bad_symbols),
                               reconciled=self.reconciler.ok, broker_error_times=self.executor.error_times)

    def _take_human_decisions(self, human: Human | None) -> None:
        for channel in self.channels:
            for hd in channel.poll():
                self.submit_human_decision(hd)
        for hd in (human(self) if human else ()):
            self.submit_human_decision(hd)

    def run(self, feed: Iterable[tuple[datetime, Mapping[str, Bar]]], human: Human | None = None,
            max_steps: int | None = None) -> RunResult:
        for i, (ts, bars) in enumerate(feed):
            if max_steps is not None and i >= max_steps:
                break
            self.step(ts, bars, human)
        return self.result()

    def result(self) -> RunResult:
        ids = [d.decision_id for d in self.decisions]
        return RunResult(
            steps=self.steps, decision_ids=ids, decision_hash=hashlib.sha256("|".join(ids).encode()).hexdigest()[:16],
            proposal_states=self.approval.counts(), orders_sent=len(self.executor.order_times), fills=len(self.fills),
            equity=round(self.ledger.equity, 2), shadow_equity=round(self.shadow_ledger.equity, 2),
            downgrades=self.policy.downgrades(), refused_decisions=self.refused,
            vetoes=veto_report(self.approval.proposals, self.shadow_ledger),
        )
