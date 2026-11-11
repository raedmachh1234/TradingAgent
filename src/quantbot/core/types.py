"""Core value types shared by every component. No behaviour beyond validation and hashing."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum, IntEnum
from typing import Any, Mapping

UTC = timezone.utc


class Mode(IntEnum):
    """Execution modes. A lower value is stricter (less autonomy)."""

    M0 = 0  # OBSERVE: log decisions, place nothing
    M1 = 1  # HUMAN-CONFIRM: nothing reaches the broker before an authenticated approval
    M2 = 2  # AUTO-WITH-LIMITS: auto-execute only while every condition holds
    M3 = 3  # FULL-AUTO: hard limits and the kill switch only

    @classmethod
    def parse(cls, value: "Mode | str | int") -> "Mode":
        if isinstance(value, Mode):
            return value
        if isinstance(value, int):
            return cls(value)
        return cls[str(value).strip().upper()]


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def sign(self) -> int:
        return 1 if self is Side.BUY else -1

    @property
    def opposite(self) -> "Side":
        return Side.SELL if self is Side.BUY else Side.BUY


class Intent(str, Enum):
    ENTRY = "ENTRY"  # opens or adds risk
    EXIT = "EXIT"    # only reduces an existing position


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


def to_jsonable(obj: Any) -> Any:
    """Convert dataclasses, enums, datetimes and containers into plain JSON types."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_jsonable(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, Enum):
        return obj.name if isinstance(obj, IntEnum) else obj.value
    if isinstance(obj, datetime):  # a naive datetime is read as UTC, never as local time
        return (obj if obj.tzinfo else obj.replace(tzinfo=UTC)).astimezone(UTC).isoformat()
    if isinstance(obj, Mapping):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, float):
        return round(obj, 10)
    if isinstance(obj, bytes):
        return obj.hex()
    return obj


def canonical_json(obj: Any) -> str:
    return json.dumps(to_jsonable(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(obj: Any, length: int = 16) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()[:length]


@dataclass(frozen=True)
class Instrument:
    symbol: str
    asset_class: str = "synthetic"
    currency: str = "EUR"
    multiplier: float = 1.0   # account-currency value of a 1.0 price move, per unit of quantity
    qty_step: float = 1.0
    min_qty: float = 1.0
    tick_size: float = 0.01
    margin_rate: float = 1.0  # 1.0 = fully funded; 0.2 = 20 % margin


@dataclass(frozen=True)
class Bar:
    symbol: str
    ts: datetime  # bar close time, timezone-aware UTC
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass(frozen=True)
class Decision:
    """What a strategy emits. It is the same object in every execution mode."""

    strategy_id: str
    strategy_version: str
    symbol: str
    side: Side
    intent: Intent
    quantity: float
    ts: datetime
    reference_price: float
    order_type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    confidence: float | None = None       # 0..1; None when the strategy has no calibrated number
    expected_value: float | None = None   # net of costs, account currency; None when unknown
    regime: str = "unknown"
    features: tuple[tuple[str, float], ...] = ()

    @property
    def decision_id(self) -> str:
        return "D-" + digest(self)

    @property
    def notional_per_unit(self) -> float:
        return self.reference_price


@dataclass(frozen=True)
class Order:
    """What the executor may send to a broker adapter, after the gate."""

    client_order_id: str
    symbol: str
    side: Side
    quantity: float
    order_type: OrderType
    strategy_id: str
    intent: Intent
    proposal_id: str
    limit_price: float | None = None
    stop_price: float | None = None
    target_price: float | None = None

    @property
    def fingerprint(self) -> str:
        core = (self.symbol, self.side, self.quantity, self.order_type, self.limit_price,
                self.stop_price, self.target_price, self.strategy_id, self.intent)
        return digest(core)


@dataclass(frozen=True)
class Fill:
    client_order_id: str
    symbol: str
    side: Side
    quantity: float
    price: float
    ts: datetime
    commission: float
    strategy_id: str
    intent: Intent
    proposal_id: str
    kind: str = "order"  # order | stop | target
    expected_price: float | None = None  # reference used to measure slippage
