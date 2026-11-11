"""Clock, event log and bus."""
from __future__ import annotations

import json
from datetime import timedelta

import pytest

from quantbot.core.bus import EventBus
from quantbot.core.clock import SimClock
from quantbot.core.eventlog import EventLog, verify_file
from quantbot.core.types import Mode, digest

from conftest import T0


def test_sim_clock_never_moves_backwards():
    c = SimClock(T0)
    c.set(T0 + timedelta(seconds=1))
    with pytest.raises(ValueError):
        c.set(T0)
    with pytest.raises(ValueError):
        c.set(T0.replace(tzinfo=None) + timedelta(days=1))


def test_mode_order_and_parsing():
    assert Mode.M0 < Mode.M1 < Mode.M2 < Mode.M3
    assert Mode.parse("m2") is Mode.M2 and Mode.parse(3) is Mode.M3 and Mode.parse(Mode.M1) is Mode.M1


def test_digest_is_stable_and_order_independent():
    assert digest({"a": 1, "b": [1, 2]}) == digest({"b": [1, 2], "a": 1})
    assert digest({"a": 1}) != digest({"a": 2})


def _log(tmp_path, n=5):
    log = EventLog(tmp_path / "events.jsonl")
    for i in range(n):
        log.append("TEST", {"i": i}, T0 + timedelta(seconds=i))
    return log


def test_event_log_chain_verifies_and_survives_reload(tmp_path):
    log = _log(tmp_path)
    assert log.verify()[0]
    assert verify_file(tmp_path / "events.jsonl")[0]
    again = EventLog(tmp_path / "events.jsonl")  # reload verifies and continues the chain
    again.append("TEST", {"i": 5}, T0 + timedelta(seconds=5))
    assert len(again) == 6 and verify_file(tmp_path / "events.jsonl")[0]


@pytest.mark.parametrize("tamper", ["edit", "delete", "reorder", "truncate_hash"])
def test_event_log_detects_tampering(tmp_path, tamper):
    _log(tmp_path)
    path = tmp_path / "events.jsonl"
    lines = path.read_text().splitlines()
    if tamper == "edit":
        rec = json.loads(lines[2]); rec["payload"]["i"] = 99; lines[2] = json.dumps(rec)
    elif tamper == "delete":
        del lines[1]
    elif tamper == "reorder":
        lines[1], lines[2] = lines[2], lines[1]
    else:
        rec = json.loads(lines[3]); rec["hash"] = "0" * 64; lines[3] = json.dumps(rec)
    path.write_text("\n".join(lines) + "\n")
    ok, why = verify_file(path)
    assert not ok, why
    with pytest.raises(ValueError):
        EventLog(path)  # a tampered log refuses to load


def test_event_log_has_no_update_or_delete_api():
    public = {n for n in dir(EventLog) if not n.startswith("_")}
    assert public == {"append", "records", "verify"}


def test_bus_is_queued_ordered_and_audits_before_dispatch():
    log, clock = EventLog(), SimClock(T0)
    bus = EventBus(log, clock)
    seen = []

    def on_a(x):
        seen.append(("a", x, len(log)))
        if x == 1:
            bus.publish("B", "from-a")  # published inside a handler: delivered after A finishes

    bus.subscribe("A", on_a)
    bus.subscribe("A", lambda x: seen.append(("a2", x, len(log))))
    bus.subscribe("B", lambda x: seen.append(("b", x, len(log))))
    bus.publish("A", 1)
    assert [s[:2] for s in seen] == [("a", 1), ("a2", 1), ("b", "from-a")]
    assert seen[0][2] == 1  # the A event was in the audit log before its first handler ran
    assert [r["type"] for r in log.records()] == ["A", "B"]
