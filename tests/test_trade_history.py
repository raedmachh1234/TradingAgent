"""The trade-history import format (docs/trade_history_format.md) and its validator."""
from __future__ import annotations

from pathlib import Path

import pytest

from quantbot.data.trade_history import load_trade_history

ROOT = Path(__file__).resolve().parents[1]
HEADER = "fill_id,timestamp,instrument,side,quantity,price,currency,commission,position_id,notes\n"


def write(tmp_path, body, header=HEADER):
    p = tmp_path / "trades.csv"
    p.write_text(header + body, encoding="utf-8")
    return p


def test_the_shipped_example_is_valid():
    rep = load_trade_history(ROOT / "docs" / "examples" / "trade_history_example.csv")
    assert rep.ok, rep.summary()
    assert len(rep.fills) == rep.rows >= 4 and rep.fills["timestamp"].is_monotonic_increasing


def test_a_valid_file_is_normalised(tmp_path):
    rep = load_trade_history(write(tmp_path, "b,2026-03-02T15:00:00+01:00,DAX,sell,1,18100,eur,1.5,p1,closing\n"
                                             "a,2026-03-02T09:00:00Z,DAX,BUY,1,18000,EUR,1.5,p1,\"note, with comma\"\n"))
    assert rep.ok, rep.summary()
    assert list(rep.fills["fill_id"]) == ["a", "b"] and list(rep.fills["side"]) == ["BUY", "SELL"]
    assert str(rep.fills["timestamp"].iloc[1]) == "2026-03-02 14:00:00+00:00" and rep.fills["currency"].iloc[1] == "EUR"


@pytest.mark.parametrize("row, column, message", [
    ("a,2026-03-02T09:00:00,DAX,BUY,1,18000,EUR,,,", "timestamp", "UTC offset"),
    ("a,02/03/2026 09:00,DAX,BUY,1,18000,EUR,,,", "timestamp", "ISO 8601"),
    ("a,2026-03-02T09:00:00Z,DAX,HOLD,1,18000,EUR,,,", "side", "must be one of"),
    ("a,2026-03-02T09:00:00Z,DAX,BUY,-1,18000,EUR,,,", "quantity", "positive"),
    ("a,2026-03-02T09:00:00Z,DAX,BUY,1,abc,EUR,,,", "price", "positive"),
    ("a,2026-03-02T09:00:00Z,DAX,BUY,1,18000,EURO,,,", "currency", "three-letter"),
    ("a,2026-03-02T09:00:00Z,DAX,BUY,1,18000,EUR,cheap,,", "commission", "number"),
    (",2026-03-02T09:00:00Z,DAX,BUY,1,18000,EUR,,,", "fill_id", "empty"),
    ("a,2026-03-02T09:00:00Z,,BUY,1,18000,EUR,,,", "instrument", "empty"),
])
def test_bad_rows_are_reported_with_row_and_column(tmp_path, row, column, message):
    rep = load_trade_history(write(tmp_path, row + "\n"))
    assert not rep.ok and rep.fills is None
    issue = next(i for i in rep.issues if i.severity == "error")
    assert issue.column == column and message in issue.message and issue.row == 2


def test_duplicates_missing_columns_and_unknown_columns(tmp_path):
    rep = load_trade_history(write(tmp_path, "a,2026-03-02T09:00:00Z,DAX,BUY,1,18000,EUR,,,\na,2026-03-02T10:00:00Z,DAX,SELL,1,18010,EUR,,,\n"))
    assert [i.row for i in rep.issues if "duplicate" in i.message] == [2, 3]
    rep = load_trade_history(write(tmp_path, "a,2026-03-02T09:00:00Z\n", header="fill_id,timestamp\n"))
    assert {i.column for i in rep.issues if i.severity == "error"} == {"instrument", "side", "quantity", "price", "currency"}
    rep = load_trade_history(write(tmp_path, "a,2026-03-02T09:00:00Z,DAX,BUY,1,18000,EUR,x\n",
                                   header="fill_id,timestamp,instrument,side,quantity,price,currency,mood\n"))
    assert rep.ok and rep.issues[0].severity == "warning" and rep.issues[0].column == "mood"


def test_unreadable_and_empty_files(tmp_path):
    p = tmp_path / "bin.csv"
    p.write_bytes(b"\xff\xfe\x00\x00garbage")
    assert not load_trade_history(p).ok
    assert "no data rows" in load_trade_history(write(tmp_path, "")).summary()
