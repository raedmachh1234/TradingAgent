"""Append-only, hash-chained audit log.

Each record carries the hash of the previous one, so removing or editing any earlier record
breaks verification. There is deliberately no update or delete API.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .types import UTC, canonical_json, to_jsonable

GENESIS = "0" * 64


def _hash(prev: str, body: dict[str, Any]) -> str:
    return hashlib.sha256((prev + canonical_json(body)).encode("utf-8")).hexdigest()


class EventLog:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else None
        self._records: list[dict[str, Any]] = []
        self._last_hash = GENESIS
        if self.path and self.path.exists():
            with open(self.path, "r", encoding="utf-8") as f:
                self._records = [json.loads(line) for line in f if line.strip()]
            ok, why = self.verify()
            if not ok:
                raise ValueError(f"event log {self.path} failed verification: {why}")
            if self._records:
                self._last_hash = self._records[-1]["hash"]
        elif self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, etype: str, payload: Any, ts: datetime) -> dict[str, Any]:
        body = {"seq": len(self._records), "ts": ts.astimezone(UTC).isoformat(), "type": etype, "payload": to_jsonable(payload)}
        record = dict(body, prev=self._last_hash, hash=_hash(self._last_hash, body))
        if self.path:
            with open(self.path, "a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
        self._records.append(record)
        self._last_hash = record["hash"]
        return record

    def records(self, etype: str | None = None) -> list[dict[str, Any]]:
        return [r for r in self._records if etype is None or r["type"] == etype]

    def __len__(self) -> int:
        return len(self._records)

    def verify(self) -> tuple[bool, str]:
        return verify_records(self._records)


def verify_records(records: list[dict[str, Any]]) -> tuple[bool, str]:
    prev = GENESIS
    for i, r in enumerate(records):
        body = {k: r.get(k) for k in ("seq", "ts", "type", "payload")}
        if r.get("seq") != i:
            return False, f"record {i}: sequence number is {r.get('seq')}"
        if r.get("prev") != prev:
            return False, f"record {i}: previous-hash link is broken"
        if r.get("hash") != _hash(prev, body):
            return False, f"record {i}: content does not match its hash"
        prev = r["hash"]
    return True, f"{len(records)} records, chain intact"


def verify_file(path: Path | str) -> tuple[bool, str]:
    with open(path, "r", encoding="utf-8") as f:
        try:
            records = [json.loads(line) for line in f if line.strip()]
        except json.JSONDecodeError as e:
            return False, f"not valid JSON lines: {e}"
    return verify_records(records)
