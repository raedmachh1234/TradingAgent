"""In-process event bus.

Publishing is queued, not recursive: an event published from inside a handler is delivered after the
current event has reached all of its subscribers. Delivery order is therefore deterministic.
Audited events are written to the append-only event log before any handler sees them.
"""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Callable

from .clock import Clock
from .eventlog import EventLog

Handler = Callable[[Any], None]


class EventBus:
    def __init__(self, log: EventLog, clock: Clock) -> None:
        self.log = log
        self.clock = clock
        self._subs: dict[str, list[Handler]] = defaultdict(list)
        self._queue: deque[tuple[str, Any]] = deque()
        self._draining = False

    def subscribe(self, etype: str, handler: Handler) -> None:
        self._subs[etype].append(handler)

    def audit(self, etype: str, payload: Any) -> None:
        """Write to the audit log without dispatching to subscribers."""
        self.log.append(etype, payload, self.clock.now())

    def publish(self, etype: str, obj: Any, audit: bool = True) -> None:
        if audit:
            self.log.append(etype, obj, self.clock.now())
        self._queue.append((etype, obj))
        if self._draining:
            return
        self._draining = True
        try:
            while self._queue:
                et, o = self._queue.popleft()
                for handler in list(self._subs.get(et, ())):
                    handler(o)
        finally:
            self._draining = False
