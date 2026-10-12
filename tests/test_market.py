import subprocess
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from scripts.daily_bars import main as daily_main

from trading_analytics.market import coverage, fetch, sessions, store, update

NOW = datetime(2030, 1, 10, 22, 0, tzinfo=UTC)  # after the close of Thu 2030-01-10
START = datetime(2030, 1, 7, 12, 0, tzinfo=UTC)


def yahoo_frame(day: date, n: int, tz="America/New_York", start="09:30", price=100.0):
    """Yahoo-style frame (tz-aware ET index, capitalised columns)."""
    idx = pd.date_range(f"{day} {start}", periods=n, freq="min", tz=tz)
    p = price + np.arange(n) * 0.25
    return pd.DataFrame(
        {"Open": p, "High": p + 1, "Low": p - 1, "Close": p + 0.25, "Volume": 10.0}, index=idx
    )


class FakeFetcher:
    """Serves minute bars for the listed days; counts calls."""

    def __init__(self, full_days=(), partial_days=None, fail_first=0):
        self.full_days, self.partial = set(full_days), partial_days or {}
        self.fail_first, self.calls = fail_first, 0

    def __call__(self, symbol, interval, start, end):
        self.calls += 1
        if self.calls <= self.fail_first:
            raise ConnectionError("transient")
        frames = [yahoo_frame(d, 390) for d in sorted(self.full_days)]
        frames += [yahoo_frame(d, n) for d, n in self.partial.items()]
        return pd.concat(frames) if frames else pd.DataFrame()


@pytest.fixture
def con():
    c = store.connect(":memory:")
    yield c
    c.close()


def count(con):
    return con.execute("SELECT count(*) FROM bars").fetchone()[0]


def test_normalize_converts_to_utc_and_drops_bad_rows():
    raw = yahoo_frame(date(2030, 1, 7), 4)
    raw.iloc[1, raw.columns.get_loc("Close")] = np.nan  # not finite
    raw.iloc[2, raw.columns.get_loc("Low")] = raw.iloc[2]["High"] + 5  # high < low
    clean, dropped = fetch.normalize(raw)
    assert dropped == 2 and len(clean) == 2
    assert str(clean.index.tz) == "UTC" and clean.index[0].hour == 14  # 09:30 ET in January
    assert clean["volume"].dtype == "int64"


def test_normalize_dedupes_and_handles_empty():
    raw = yahoo_frame(date(2030, 1, 7), 3)
    dup = pd.concat([raw, raw.iloc[[1]]])
    assert len(fetch.normalize(dup)[0]) == 3
    assert fetch.normalize(pd.DataFrame())[0].empty


def test_retry_recovers_after_transient_failures():
    sleeps = []
    f = FakeFetcher(full_days=[date(2030, 1, 7)], fail_first=2)
    out = fetch.fetch_with_retry(f, "NQ=F", "1m", START, NOW, sleep=sleeps.append)
    assert not out.empty and f.calls == 3
    assert sleeps == [2.0, 4.0]  # exponential backoff


def test_retry_gives_up_with_clear_error():
    f = FakeFetcher(fail_first=99)
    with pytest.raises(fetch.FetchError, match="failed after 3 attempts"):
        fetch.fetch_with_retry(f, "NQ=F", "1m", START, NOW, attempts=3, sleep=lambda s: None)
    assert f.calls == 3


def test_empty_result_is_retried_only_when_data_is_expected():
    f = FakeFetcher()
    with pytest.raises(fetch.FetchError):
        fetch.fetch_with_retry(f, "NQ=F", "1m", START, NOW, attempts=2, sleep=lambda s: None)
    f2 = FakeFetcher()
    out = fetch.fetch_with_retry(f2, "NQ=F", "1m", START, NOW, expects_data=False)
    assert out.empty and f2.calls == 1  # a weekend/holiday window is legitimately empty


def test_chunking_respects_request_limit_and_clamps_to_yahoo_history():
    start = NOW - timedelta(days=20)
    w = fetch.chunk_windows("1m", start, NOW, NOW)
    assert all(x.end - x.start <= timedelta(days=7) for x in w)
    assert w[0].start == start and w[-1].end == NOW
    assert all(a.end == b.start for a, b in zip(w, w[1:], strict=False))  # contiguous, no gaps
    old = fetch.chunk_windows("1m", NOW - timedelta(days=90), NOW, NOW)
    assert old[0].start == NOW - timedelta(days=29)


def test_upsert_is_idempotent(con):
    bars, _ = fetch.normalize(yahoo_frame(date(2030, 1, 7), 390))
    ts = pd.Timestamp(NOW)
    assert store.upsert_bars(con, "NQ=F", "1m", bars, ts) == 390
    store.upsert_bars(con, "NQ=F", "1m", bars, ts)
    store.upsert_bars(con, "NQ=F", "1m", bars, ts)
    assert count(con) == 390


def test_upsert_overwrites_revised_bar_and_keeps_series_separate(con):
    bars, _ = fetch.normalize(yahoo_frame(date(2030, 1, 7), 3))
    store.upsert_bars(con, "NQ=F", "1m", bars, pd.Timestamp(NOW))
    revised = bars.copy()
    revised.iloc[-1, revised.columns.get_loc("close")] = 999.0
    store.upsert_bars(con, "NQ=F", "1m", revised, pd.Timestamp(NOW))
    store.upsert_bars(con, "NQ=F", "5m", bars, pd.Timestamp(NOW))  # same ts, other interval
    assert count(con) == 6
    last = con.execute(
        "SELECT close FROM bars WHERE interval='1m' ORDER BY ts DESC LIMIT 1"
    ).fetchone()[0]
    assert last == 999.0


def run_update(con, fetcher, now=NOW, start=START):
    return update.update_bars(
        con,
        fetcher,
        start,
        now,
        first_session=date(2030, 1, 7),
        targets=[("NQ=F", "1m")],
        sleep=lambda s: None,
    )


def statuses(report):
    return report.coverage.set_index("session_date")["status"].to_dict()


def test_coverage_flags_missing_partial_ok_and_skips_non_trading_days(con):
    f = FakeFetcher(full_days=[date(2030, 1, 7)], partial_days={date(2030, 1, 9): 100})
    report = run_update(con, f)
    s = statuses(report)
    assert s == {
        date(2030, 1, 7): "ok",
        date(2030, 1, 8): "missing",  # nothing returned for a trading day
        date(2030, 1, 9): "partial",
        date(2030, 1, 10): "missing",
    }
    assert not report.ok and set(report.flagged["session_date"]) == {
        date(2030, 1, 8),
        date(2030, 1, 9),
        date(2030, 1, 10),
    }


def test_weekend_and_holiday_are_not_expected(con):
    days = sessions.expected_trading_days(date(2026, 12, 24), date(2027, 1, 4))
    assert date(2026, 12, 25) not in days and date(2027, 1, 1) not in days
    assert date(2026, 12, 26) not in days and date(2026, 12, 28) in days
    assert sessions.expected_rth_bars(date(2026, 12, 24), 1) == 225  # early close 13:15 ET


def test_session_still_running_is_in_progress_not_missing(con):
    now = datetime(2030, 1, 10, 16, 0, tzinfo=UTC)  # 11:00 ET
    f = FakeFetcher(full_days=[date(2030, 1, 7), date(2030, 1, 8), date(2030, 1, 9)])
    s = statuses(run_update(con, f, now=now))
    assert s[date(2030, 1, 10)] == "in_progress"
    assert set(s.values()) == {"ok", "in_progress"}


def test_unrecoverable_gap_is_marked(con):
    old_now = datetime(2030, 1, 30, 22, 0, tzinfo=UTC)
    rows = coverage.refresh_coverage(
        con, "NQ=F", "1m", date(2030, 1, 7), date(2030, 1, 30), old_now
    )
    jan7 = rows.set_index("session_date").loc[date(2030, 1, 7)]
    assert jan7["status"] == "missing" and not jan7["recoverable"]  # 1m window is ~7 days
    assert rows.set_index("session_date").loc[date(2030, 1, 29)]["recoverable"]


def test_update_twice_is_idempotent_and_fixes_gaps_later(con):
    f1 = FakeFetcher(full_days=[date(2030, 1, 7)])
    run_update(con, f1)
    before = count(con)
    run_update(con, f1)
    assert count(con) == before
    f2 = FakeFetcher(full_days=[date(2030, 1, 7), date(2030, 1, 8)])  # the gap is backfilled
    report = run_update(con, f2)
    assert statuses(report)[date(2030, 1, 8)] == "ok"
    assert count(con) == before + 390


def test_failed_fetch_is_reported_not_swallowed(con):
    report = run_update(con, FakeFetcher(fail_first=99))
    assert ("NQ=F", "1m") in report.errors and not report.ok
    assert count(con) == 0


def test_script_exit_codes_and_no_network(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(fetch._time, "sleep", lambda s: None)  # no real backoff waits
    db = str(tmp_path / "m.duckdb")
    assert daily_main(["--db", db], fetcher=FakeFetcher(fail_first=99)) == 1
    out = capsys.readouterr().out
    assert "ERROR" in out


def test_real_bar_stores_are_gitignored():
    for path in ("data/warehouse/market.duckdb", "data/warehouse/market.duckdb.wal"):
        r = subprocess.run(["git", "check-ignore", "-q", path])
        assert r.returncode == 0, f"{path} must be gitignored"
