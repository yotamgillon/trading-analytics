"""The scheduled job: fetch -> validate -> idempotent upsert -> coverage flags."""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import duckdb
import pandas as pd

from trading_analytics.market import coverage, fetch, sessions, store

log = logging.getLogger(__name__)

# User trades NQ/MNQ, which track the same index; the NQ future covers both.
DEFAULT_TARGETS = [("NQ=F", "1m"), ("NQ=F", "5m"), ("^VIX", "1d")]


@dataclass
class UpdateReport:
    rows_written: dict[tuple[str, str], int] = field(default_factory=dict)
    rows_dropped: dict[tuple[str, str], int] = field(default_factory=dict)
    errors: dict[tuple[str, str], str] = field(default_factory=dict)
    coverage: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def flagged(self) -> pd.DataFrame:
        if self.coverage.empty:
            return self.coverage
        return self.coverage[self.coverage["status"].isin(["missing", "partial"])]

    @property
    def ok(self) -> bool:
        return not self.errors and self.flagged.empty


def update_bars(
    con: duckdb.DuckDBPyConnection,
    fetcher: fetch.Fetcher,
    start: datetime,
    now: datetime,
    first_session: date | None = None,
    targets: list[tuple[str, str]] = DEFAULT_TARGETS,
    sleep: Callable[[float], None] | None = None,
) -> UpdateReport:
    report = UpdateReport()
    sleep = sleep or fetch._time.sleep  # looked up at call time so tests can patch it
    first_session = first_session or start.astimezone(sessions.ET).date()
    end = now + timedelta(days=1)  # Yahoo's end is exclusive
    frames = []
    for symbol, interval in targets:
        key = (symbol, interval)
        report.rows_written[key] = report.rows_dropped[key] = 0
        for w in fetch.chunk_windows(interval, start, end, now):
            days = sessions.expected_trading_days(
                w.start.astimezone(sessions.ET).date(),
                (w.end - timedelta(seconds=1)).astimezone(sessions.ET).date(),
            )
            try:
                raw = fetch.fetch_with_retry(
                    fetcher, symbol, interval, w.start, w.end, expects_data=bool(days), sleep=sleep
                )
            except fetch.FetchError as exc:
                report.errors[key] = str(exc)
                log.error("%s", exc)
                continue
            clean, dropped = fetch.normalize(raw)
            report.rows_dropped[key] += dropped
            report.rows_written[key] += store.upsert_bars(
                con, symbol, interval, clean, pd.Timestamp(now)
            )
        frames.append(
            coverage.refresh_coverage(
                con,
                symbol,
                interval,
                first_session,
                now.astimezone(sessions.ET).date(),
                now,
            )
        )
    report.coverage = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return report
