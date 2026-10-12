"""Daily bar accumulation job. Run: make bars   (or schedule it, see CLAUDE.md).

Fetches Yahoo bars since --start (default: 6 days ago, inside the 1-minute window), upserts them
into the gitignored warehouse and prints coverage flags. Idempotent: safe to run any number of
times. Exit code 1 if a fetch failed or an expected trading day is missing/partial.
"""

import argparse
import logging
import sys
from datetime import UTC, date, datetime, time, timedelta

from trading_analytics.market import fetch, sessions, store, update


def main(argv: list[str] | None = None, fetcher: fetch.Fetcher = fetch.yahoo_fetcher) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=date.fromisoformat, help="first session date, e.g. 2026-10-08")
    ap.add_argument("--db", default=str(store.DEFAULT_DB))
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    now = datetime.now(UTC)
    start_day = args.start or (now - timedelta(days=6)).date()
    # A session's Globex day opens at 18:00 ET the evening before: fetch from just before it.
    start = datetime.combine(start_day - timedelta(days=1), time(17, 0), tzinfo=sessions.ET)

    con = store.connect(args.db)
    report = update.update_bars(con, fetcher, start, now, first_session=start_day)

    for (symbol, interval), n in report.rows_written.items():
        dropped = report.rows_dropped[(symbol, interval)]
        print(f"{symbol} {interval}: {n} rows upserted, {dropped} dropped")
    for key, msg in report.errors.items():
        print(f"ERROR {key}: {msg}")
    c = report.coverage
    if not c.empty:
        counts = c.groupby(["symbol", "interval", "status"]).size().unstack(fill_value=0)
        print("\nCoverage by status:\n" + counts.to_string())
        if not report.flagged.empty:
            cols = [
                "symbol",
                "interval",
                "session_date",
                "expected_bars",
                "actual_bars",
                "status",
                "recoverable",
            ]
            print("\nFLAGGED DAYS:\n" + report.flagged[cols].to_string(index=False))
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
