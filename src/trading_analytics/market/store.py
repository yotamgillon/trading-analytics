"""DuckDB bar store: idempotent upserts keyed by (symbol, interval, ts).

Re-running a fetch never duplicates rows; a re-fetched bar overwrites the stored one because
Yahoo revises the most recent bars. The store lives in the gitignored warehouse: real bars are
never committed.
"""

from pathlib import Path

import duckdb
import pandas as pd

DEFAULT_DB = Path("data/warehouse/market.duckdb")

SCHEMA = """
CREATE TABLE IF NOT EXISTS bars (
    symbol VARCHAR NOT NULL,
    interval VARCHAR NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    open DOUBLE NOT NULL,
    high DOUBLE NOT NULL,
    low DOUBLE NOT NULL,
    close DOUBLE NOT NULL,
    volume BIGINT NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (symbol, interval, ts)
);
CREATE TABLE IF NOT EXISTS bar_coverage (
    symbol VARCHAR NOT NULL,
    interval VARCHAR NOT NULL,
    session_date DATE NOT NULL,
    expected_bars INTEGER NOT NULL,
    actual_bars INTEGER NOT NULL,
    ratio DOUBLE NOT NULL,
    status VARCHAR NOT NULL,       -- ok | partial | missing | in_progress
    recoverable BOOLEAN NOT NULL,  -- can Yahoo still serve this day?
    checked_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (symbol, interval, session_date)
);
"""


def connect(path: str | Path = DEFAULT_DB) -> duckdb.DuckDBPyConnection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute("SET TimeZone = 'UTC'")
    con.execute(SCHEMA)
    return con


def upsert_bars(
    con: duckdb.DuckDBPyConnection,
    symbol: str,
    interval: str,
    bars: pd.DataFrame,
    fetched_at: pd.Timestamp,
) -> int:
    """Insert or overwrite bars (index = UTC ts). Returns the number of rows written."""
    if bars.empty:
        return 0
    frame = bars.reset_index(names="ts").assign(
        symbol=symbol, interval=interval, fetched_at=fetched_at
    )[["symbol", "interval", "ts", "open", "high", "low", "close", "volume", "fetched_at"]]
    con.register("incoming_bars", frame)
    try:
        con.execute(
            """
            INSERT INTO bars SELECT * FROM incoming_bars
            ON CONFLICT (symbol, interval, ts) DO UPDATE SET
                open = excluded.open, high = excluded.high, low = excluded.low,
                close = excluded.close, volume = excluded.volume,
                fetched_at = excluded.fetched_at
            """
        )
    finally:
        con.unregister("incoming_bars")
    return len(frame)
