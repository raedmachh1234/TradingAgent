"""Clocks. Every component takes time from a Clock, so replay is deterministic."""
from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .types import UTC


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class SimClock:
    """A clock that only moves when told to, and never backwards."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2000, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def set(self, ts: datetime) -> None:
        if ts.tzinfo is None:
            raise ValueError("clock times must be timezone-aware")
        if ts < self._now:
            raise ValueError(f"clock cannot move backwards: {ts} < {self._now}")
        self._now = ts
