"""Strategy registry. Strategies are created only from registered classes, never from arbitrary import paths."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Type

from .base import Strategy

_CLASSES: dict[str, Type[Strategy]] = {}
STATUSES = ("candidate", "paper", "shadow", "live")  # informational; autonomy comes only from signed grants


def register(name: str) -> Callable[[Type[Strategy]], Type[Strategy]]:
    def deco(cls: Type[Strategy]) -> Type[Strategy]:
        if name in _CLASSES and _CLASSES[name] is not cls:
            raise ValueError(f"strategy class name already registered: {name}")
        _CLASSES[name] = cls
        return cls
    return deco


@dataclass
class Entry:
    strategy: Strategy
    weight: float
    status: str
    enabled: bool = True


class StrategyRegistry:
    def __init__(self) -> None:
        self._entries: dict[str, Entry] = {}

    def add(self, strategy: Strategy, weight: float = 1.0, status: str = "candidate") -> None:
        if strategy.id in self._entries:
            raise ValueError(f"duplicate strategy id: {strategy.id}")
        if status not in STATUSES:
            raise ValueError(f"unknown status {status!r}; expected one of {STATUSES}")
        if weight <= 0:
            raise ValueError("weight must be positive")
        self._entries[strategy.id] = Entry(strategy, float(weight), status)

    def get(self, strategy_id: str) -> Entry:
        return self._entries[strategy_id]

    def active(self) -> list[Entry]:
        return [e for e in self._entries.values() if e.enabled]

    def ids(self) -> list[str]:
        return list(self._entries)

    @classmethod
    def from_config(cls, specs: list[Mapping[str, Any]]) -> "StrategyRegistry":
        from .. import strategies  # noqa: F401  (imports register the built-in classes)

        reg = cls()
        for spec in specs:
            name = spec["class"]
            if name not in _CLASSES:
                raise ValueError(f"unknown strategy class {name!r}; registered: {sorted(_CLASSES)}")
            strat = _CLASSES[name](spec["id"], str(spec.get("version", "0")), list(spec["symbols"]), spec.get("params", {}))
            reg.add(strat, weight=spec.get("weight", 1.0), status=spec.get("status", "candidate"))
        return reg
