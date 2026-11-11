"""Broker adapter interface. Each adapter declares which execution modes it can support.

Only the executor is allowed to hold an adapter. Strategies never see one.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..core.types import Bar, Fill, Mode, Order


class BrokerError(Exception):
    pass


@dataclass(frozen=True)
class BrokerCapabilities:
    name: str
    supported_modes: frozenset[Mode]
    is_paper: bool
    has_order_api: bool = True
    # False for anything that keeps trading on its own once started, outside the gate, the kill switch and
    # reconciliation: a live ProOrder script on ProRealTime's servers is the case in point. Such an adapter is
    # treated as M3 and is usable only by a strategy holding a signed M3 grant (owner decision 5, 2026-11-10).
    gate_controlled: bool = True

    def max_mode(self) -> Mode:
        return max(self.supported_modes)


@dataclass(frozen=True)
class OrderAck:
    client_order_id: str
    accepted: bool
    duplicate: bool = False
    message: str = ""


class BrokerAdapter(ABC):
    capabilities: BrokerCapabilities

    @abstractmethod
    def submit(self, order: Order) -> OrderAck: ...

    @abstractmethod
    def cancel(self, client_order_id: str) -> bool: ...

    @abstractmethod
    def positions(self) -> dict[str, float]: ...

    @abstractmethod
    def open_orders(self) -> list[Order]: ...

    def on_bar(self, bar: Bar) -> list[Fill]:
        """Simulated venues advance on bars. Live adapters return fills from the broker instead."""
        return []


# Declared now so the policy can already be tested against them; the adapters themselves come with the broker phase.
PROREALTIME_TICKET = BrokerCapabilities("prorealtime-ticket", frozenset({Mode.M0, Mode.M1}), is_paper=False, has_order_api=False)
PROORDER_LIVE_SCRIPT = BrokerCapabilities("proorder-live-script", frozenset({Mode.M3}), is_paper=False, has_order_api=False,
                                          gate_controlled=False)
