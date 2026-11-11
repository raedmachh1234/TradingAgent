"""The cached data layer: fallback, lineage, incremental append, conflicts, quality checks, point-in-time views."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from quantbot.core.clock import SimClock
from quantbot.data.providers import CsvProvider, FailingProvider, SyntheticProvider
from quantbot.data.quality import check_bars, is_stale
from quantbot.data.service import DataService, DataUnavailable, History, replay_feed
from quantbot.data.store import DataStore

UTC = timezone.utc
JAN, JUN, DEC = (datetime(2025, m, d, tzinfo=UTC) for m, d in ((1, 1), (6, 30), (12, 31)))


def svc(tmp_path, providers, now=datetime(2026, 1, 1, tzinfo=UTC)):
    store = DataStore(tmp_path / "cache")
    return store, DataService(store, providers, SimClock(now), "1d", {"max_gap_factor": 3.0, "outlier_mad": 12.0, "outlier_min_abs": 0.08})


class BadProvider:
    name, terms = "bad", "test"

    def fetch_bars(self, symbol, start, end, freq):
        df = SyntheticProvider().fetch_bars(symbol, start, end, freq)
        df.loc[3, "high"] = df.loc[3, "low"] * 0.5  # high below low
        return df


class CountingProvider(SyntheticProvider):
    name = "counting"

    def __init__(self):
        super().__init__()
        self.calls = []

    def fetch_bars(self, symbol, start, end, freq):
        self.calls.append((start, end))
        return super().fetch_bars(symbol, start, end, freq)


def test_fallback_to_next_provider_is_recorded(tmp_path):
    store, s = svc(tmp_path, [FailingProvider("down"), SyntheticProvider()])
    r = s.ensure_bars("d", "X", JAN, DEC)
    assert r.ingests[0].provider == "synthetic" and r.ingests[0].fallback_errors == ("down: simulated outage",)
    assert r.ingests[0].rows_total == len(s.bars("d", "X")) > 250
    log = store.ingests()
    assert log.loc[0, "fallback_errors"] == "down: simulated outage"


def test_bad_data_from_a_provider_is_rejected_and_the_next_one_used(tmp_path):
    _, s = svc(tmp_path, [BadProvider(), SyntheticProvider()])
    r = s.ensure_bars("d", "X", JAN, JUN)
    assert r.ingests[0].provider == "synthetic"
    assert "ohlc_inconsistent" in r.errors[0]


def test_all_providers_failing_raises(tmp_path):
    _, s = svc(tmp_path, [FailingProvider("a"), FailingProvider("b")])
    with pytest.raises(DataUnavailable, match="a: simulated outage .* b: simulated outage"):
        s.ensure_bars("d", "X", JAN, DEC)


def test_every_row_records_provider_and_retrieval_time_and_the_catalog_records_terms(tmp_path):
    store, s = svc(tmp_path, [SyntheticProvider()])
    s.ensure_bars("d", "X", JAN, DEC)
    df = s.bars("d", "X")
    assert set(df["provider"]) == {"synthetic"}
    assert set(df["retrieved_at"]) == {pd.Timestamp("2026-01-01")}
    man = store.manifest()
    assert man.loc[0, "terms"] == SyntheticProvider.terms and man.loc[0, "ingests"] == 1


def test_cache_hit_and_incremental_append(tmp_path):
    p = CountingProvider()
    store, s = svc(tmp_path, [p])
    first = s.ensure_bars("d", "X", JAN, JUN)
    n1 = first.ingests[0].rows_total
    assert s.ensure_bars("d", "X", JAN, JUN).cache_hit
    later = s.ensure_bars("d", "X", JAN, DEC)
    assert not later.cache_hit and len(p.calls) == 2
    assert p.calls[1] == (datetime(2025, 6, 27, 21, tzinfo=UTC), DEC)  # only the tail, from the last bar held
    assert later.ingests[0].rows_total > n1 and later.ingests[0].rows_added == later.ingests[0].rows_total - n1
    ts = s.bars("d", "X")["ts"]
    assert ts.is_monotonic_increasing and not ts.duplicated().any()


def test_redelivered_bars_never_rewrite_history(tmp_path):
    store, s = svc(tmp_path, [SyntheticProvider()])
    s.ensure_bars("d", "X", JAN, JUN)
    before = s.bars("d", "X")
    changed = SyntheticProvider(seed=99).fetch_bars("X", JAN, JUN, "1d")  # same timestamps, different prices
    rec = store.write_bars("d", "X", changed, provider="other", terms="t", retrieved_at=datetime(2026, 2, 1, tzinfo=UTC))
    assert rec.rows_added == 0 and rec.conflicts == len(changed)
    after = s.bars("d", "X")
    pd.testing.assert_frame_equal(before, after)


def test_point_in_time_view_of_the_cache(tmp_path):
    store, s = svc(tmp_path, [SyntheticProvider()])
    s.ensure_bars("d", "X", JAN, JUN)
    s.clock.set(datetime(2026, 3, 1, tzinfo=UTC))
    s.ensure_bars("d", "X", JAN, DEC)
    as_of_jan = store.read_bars("d", "X", retrieved_before=datetime(2026, 1, 15, tzinfo=UTC))
    assert as_of_jan["ts"].max() <= datetime(2025, 7, 1, tzinfo=UTC)
    assert len(store.read_bars("d", "X")) > len(as_of_jan)


def test_synthetic_provider_is_deterministic_and_window_independent():
    p = SyntheticProvider(seed=7)
    full = p.fetch_bars("X", JAN, DEC, "1d")
    part = p.fetch_bars("X", JUN, DEC, "1d")
    again = SyntheticProvider(seed=7).fetch_bars("X", JAN, DEC, "1d")
    pd.testing.assert_frame_equal(full, again)
    tail = full[full.ts >= part.ts.iloc[0]].reset_index(drop=True)
    pd.testing.assert_frame_equal(tail, part)
    assert not full.equals(SyntheticProvider(seed=8).fetch_bars("X", JAN, DEC, "1d"))
    assert check_bars(full).ok


def test_csv_provider(tmp_path):
    df = SyntheticProvider().fetch_bars("X", JAN, JUN, "1d")
    (tmp_path / "csv").mkdir()
    df.assign(ts=df.ts.dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")).to_csv(tmp_path / "csv" / "X.csv", index=False)
    got = CsvProvider(tmp_path / "csv").fetch_bars("X", JAN, JUN, "1d")
    assert len(got) == len(df) and np.allclose(got.close, df.close)
    with pytest.raises(Exception, match="no file"):
        CsvProvider(tmp_path / "csv").fetch_bars("Y", JAN, JUN, "1d")


def good_frame(n=40):
    return SyntheticProvider().fetch_bars("X", JAN, JAN + timedelta(days=int(n * 1.5)), "1d").head(n).copy()


@pytest.mark.parametrize("mutate, code, severity", [
    (lambda d: d.__setitem__("close", d["close"].where(d.index != 5, np.nan)), "nan_price", "fatal"),
    (lambda d: d.__setitem__("low", d["low"].where(d.index != 5, -1.0)), "non_positive_price", "fatal"),
    (lambda d: d.__setitem__("volume", d["volume"].where(d.index != 5, -10.0)), "negative_volume", "fatal"),
    (lambda d: d.__setitem__("high", d["high"].where(d.index != 5, d["low"] * 0.9)), "ohlc_inconsistent", "fatal"),
    (lambda d: d.__setitem__("ts", d["ts"].where(d.index != 6, d["ts"].iloc[5])), "duplicate_ts", "fatal"),
    (lambda d: d.__setitem__("ts", d["ts"].where(d.index != 6, d["ts"].iloc[2])), "non_monotonic_ts", "fatal"),
    (lambda d: d.__setitem__("ts", d["ts"].where(d.index < 20, d["ts"] + pd.Timedelta(days=30))), "gap", "warn"),
    (lambda d: d.__setitem__("volume", d["volume"].where(d.index != 5, 0.0)), "zero_volume", "warn"),
])
def test_quality_checks(mutate, code, severity):
    df = good_frame()
    mutate(df)
    rep = check_bars(df)
    issue = next(i for i in rep.issues if i.code == code)
    assert issue.severity == severity
    assert rep.ok is (severity == "warn")


def test_quality_flags_an_outlier_return():
    df = good_frame()
    for col in ("open", "high", "low", "close"):
        df.loc[20:, col] = df.loc[20:, col] * 1.5  # a 50 % jump that never reverses, e.g. an unadjusted split
    assert "outlier_return" in check_bars(df).codes


def test_staleness():
    now = datetime(2025, 1, 10, tzinfo=UTC)
    assert is_stale(None, now, 60)
    assert is_stale(now - timedelta(seconds=61), now, 60) and not is_stale(now - timedelta(seconds=59), now, 60)


def test_replay_is_in_time_order_and_history_has_no_future(tmp_path):
    store, s = svc(tmp_path, [SyntheticProvider()])
    for sym in ("A", "B"):
        s.ensure_bars("d", sym, JAN, JUN)
    hist, last = History(), None
    for ts, bars in replay_feed(store, "d", ["A", "B"]):
        assert last is None or ts > last
        for b in bars.values():
            hist.append(b)
        assert all(b.ts <= ts for b in hist.bars("A") + hist.bars("B"))
        last = ts
    assert len(hist.bars("A")) == len(s.bars("d", "A"))
