"""Missing-day flagging: compare stored bars against the days that should exist."""

from datetime import date, datetime, timedelta

import duckdb
import pandas as pd

from trading_analytics.market.fetch import INTERVAL_MINUTES, LIMITS
from trading_analytics.market.sessions import (
    ET,
    expected_rth_bars,
    expected_trading_days,
    rth_window_utc,
)

OK_RATIO = 0.98


def _status(expected: int, actual: int, d: date, now: datetime) -> str:
    _, close_utc = rth_window_utc(d)
    if now < close_utc + timedelta(minutes=5):
        return "in_progress"  # the session is not over: do not call it a gap yet
    if actual == 0:
        return "missing"
    return "ok" if actual / expected >= OK_RATIO else "partial"


def refresh_coverage(
    con: duckdb.DuckDBPyConnection,
    symbol: str,
    interval: str,
    start: date,
    end: date,
    now: datetime,
) -> pd.DataFrame:
    """Recompute and store one coverage row per expected trading day in [start, end]."""
    minutes = INTERVAL_MINUTES[interval]
    rows = []
    for d in expected_trading_days(start, end):
        if interval == "1d":
            expected = 1
            actual = con.execute(
                "SELECT count(*) FROM bars WHERE symbol=? AND interval=? "
                "AND CAST(ts AT TIME ZONE 'America/New_York' AS DATE) = ?",
                [symbol, interval, d],
            ).fetchone()[0]
        else:
            expected = expected_rth_bars(d, minutes)
            lo, hi = rth_window_utc(d)
            actual = con.execute(
                "SELECT count(*) FROM bars WHERE symbol=? AND interval=? AND ts >= ? AND ts < ?",
                [symbol, interval, lo, hi],
            ).fetchone()[0]
        recoverable_from = (now - timedelta(days=LIMITS[interval][2])).astimezone(ET).date()
        rows.append(
            (
                symbol,
                interval,
                d,
                expected,
                actual,
                actual / expected,
                _status(expected, actual, d, now),
                d >= recoverable_from,
                now,
            )
        )
    for r in rows:
        con.execute("INSERT OR REPLACE INTO bar_coverage VALUES (?,?,?,?,?,?,?,?,?)", list(r))
    return pd.DataFrame(
        rows,
        columns=[
            "symbol",
            "interval",
            "session_date",
            "expected_bars",
            "actual_bars",
            "ratio",
            "status",
            "recoverable",
            "checked_at",
        ],
    )
