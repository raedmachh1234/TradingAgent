"""Exit test of the book foundation: every chapter's method beats the naive baseline it replaces."""
import pytest

from quantbot.foundation import CHAPTERS


def test_every_chapter_declares_its_assumption_and_baseline():
    for number, mod in CHAPTERS.items():
        assert mod.CHAPTER == number
        assert mod.TITLE and mod.ASSUMPTION and mod.BASELINE
        assert callable(mod.check) and callable(mod.beat_baseline)


@pytest.mark.parametrize("chapter", sorted(CHAPTERS))
def test_every_chapter_beats_its_baseline(chapter):
    results = CHAPTERS[chapter].beat_baseline(seed=0)
    assert results
    for r in results:
        assert r.chapter == chapter
        assert r.beats, f"{r.method} {r.method_score} vs {r.baseline} {r.baseline_score} ({r.metric})"
        assert r.wins is None or r.wins >= 0.6, f"{r.method} wins only {r.wins:.0%} of cases"


@pytest.mark.parametrize("chapter", [1, 3, 4, 5, 6, 7, 11, 13, 14])
def test_the_result_does_not_depend_on_the_seed(chapter):
    assert all(r.beats for r in CHAPTERS[chapter].beat_baseline(seed=1))
