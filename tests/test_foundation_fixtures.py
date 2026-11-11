"""The book's 57 worked answers, re-computed through the chapter modules (not through the Phase 0 script)."""
import math

import pytest

from quantbot.foundation import CHAPTERS, fixtures

ROWS = fixtures.load()


def test_every_fixture_has_exactly_one_library_call():
    assert len(ROWS) == 57
    assert {r["id"] for r in ROWS} == set(fixtures.CALLS)


def test_fixtures_cover_all_17_chapters():
    assert {r["chapter"] for r in ROWS} == set(CHAPTERS) == set(range(1, 18))


@pytest.mark.parametrize("row", ROWS, ids=[r["id"] for r in ROWS])
def test_library_reproduces_the_book(row):
    value = float(fixtures.CALLS[row["id"]]())
    assert abs(value - row["printed"]) <= row["tol"], f"{row['quantity']}: {value} vs printed {row['printed']}"
    assert math.isclose(value, row["computed"], rel_tol=1e-9, abs_tol=1e-12), "differs from the Phase 0 check"


def test_reproduce_reports_every_row():
    rows = fixtures.reproduce()
    assert len(rows) == 57 and all(r["reproduces"] and r["matches_phase0"] for r in rows)
