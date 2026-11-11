"""Executor: the only component that holds a broker adapter.

It sends an order only when all of these hold: the order has not been sent before (idempotent on
client_order_id), it comes with a genuine, fresh, passing risk verdict for exactly that order, the kill
switch allows it, and the order-rate limit is not exceeded.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from ..brokers.base import BrokerAdapter, BrokerCapabilities, BrokerError, OrderAck
from ..core.bus import EventBus
from ..core.clock import Clock
from ..core.types import Bar, Fill, Intent, Order
from ..risk.gate import RiskGate, RiskVerdict


class ExecutionRefused(Exception):
    """The executor declined to send the order."""


class ExecutionFailed(Exception):
    """The broker raised an error."""


class Executor:
    def __init__(self, broker: BrokerAdapter, risk_gate: RiskGate, clock: Clock, bus: EventBus,
                 verdict_max_age_seconds: float = 5.0) -> None:
        self.__broker = broker
        self._risk, self._clock, self._bus = risk_gate, clock, bus
        self._max_age = float(verdict_max_age_seconds)
        self._acks: dict[str, OrderAck] = {}
        self.order_times: list[datetime] = []
        self.error_times: list[datetime] = []

    @property
    def capabilities(self) -> BrokerCapabilities:
        return self.__broker.capabilities

    def submit(self, order: Order, verdict: RiskVerdict) -> OrderAck:
        now = self._clock.now()
        if order.client_order_id in self._acks:
            self._bus.audit("ORDER_DUPLICATE_SUPPRESSED", {"client_order_id": order.client_order_id, "proposal": order.proposal_id})
            return replace(self._acks[order.client_order_id], duplicate=True)

        def refuse(why: str) -> None:
            self._bus.audit("ORDER_REFUSED", {"client_order_id": order.client_order_id, "proposal": order.proposal_id, "reason": why})
            raise ExecutionRefused(why)

        ok, why = self._risk.verify(verdict, order, now, self._max_age)
        if not ok:
            refuse(why)
        limits = self._risk.limits
        if self._risk.kill_switch.engaged and not (order.intent is Intent.EXIT and limits.kill_switch_allows_exits):
            refuse("kill switch is engaged")
        if sum(1 for t in self.order_times if (now - t).total_seconds() < 60.0) >= limits.max_orders_per_minute:
            refuse("order rate limit")
        try:
            ack = self.__broker.submit(order)
        except BrokerError as exc:
            self.error_times.append(now)
            self._bus.audit("ORDER_FAILED", {"client_order_id": order.client_order_id, "proposal": order.proposal_id, "error": str(exc)})
            raise ExecutionFailed(str(exc)) from exc
        self._acks[order.client_order_id] = ack
        if ack.accepted:
            self.order_times.append(now)
        self._bus.audit("ORDER_SUBMITTED" if ack.accepted else "ORDER_REJECTED", {"order": order, "message": ack.message})
        return ack

    def cancel(self, client_order_id: str) -> bool:
        done = self.__broker.cancel(client_order_id)
        self._bus.audit("ORDER_CANCEL", {"client_order_id": client_order_id, "done": done})
        return done

    def on_bar(self, bar: Bar) -> list[Fill]:
        return self.__broker.on_bar(bar)

    def drain_cancelled(self) -> list[str]:
        drain = getattr(self.__broker, "drain_cancelled", None)
        return drain() if drain else []

    def broker_positions(self) -> dict[str, float]:
        return self.__broker.positions()

    def orders_on(self, day, tz) -> int:
        return sum(1 for t in self.order_times if t.astimezone(tz).date() == day)
