"""Load a dataset (demo or private) into DuckDB so dbt can model it.

Schemas written here (dbt never writes to them):
  raw     as exported / as fetched: fills_raw (strings), bars_1m, vix_daily
  ingest  Python-derived: fills (cleaned canonical), trades (paired), open_positions,
          quality_findings. FIFO pairing is stateful, so it stays in Python; all analytics are SQL.
dbt then builds staging -> intermediate -> marts from these.
"""

from dataclasses import dataclass
from pathlib import Path

import duckdb
import pandas as pd

from trading_analytics.market import store
from trading_analytics.quality.pipeline import IngestResult, ingest_file

DATASETS = {
    "demo": {"fills": Path("data/demo/Fills.csv"), "db": Path("data/warehouse/demo.duckdb")},
    "private": {
        "fills": Path("data/private/Fills.csv"),
        "db": Path("data/warehouse/private.duckdb"),
    },
}
BAR_SYMBOL = "NQ=F"  # NQ and MNQ both trade the Nasdaq-100: NQ bars are the proxy for MNQ


@dataclass
class BuildSummary:
    dataset: str
    db_path: Path
    n_fills: int
    n_trades: int
    n_bars: int
    n_vix: int
    ingest: IngestResult


def _demo_market() -> tuple[pd.DataFrame, pd.DataFrame]:
    bars = pd.read_parquet("data/demo/bars_1m.parquet")
    vix = pd.read_parquet("data/demo/vix_daily.parquet")
    return bars, vix


def _real_market(market_db: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Bars accumulated by `make bars` (gitignored store). Empty frames if there are none."""
    if not market_db.exists():
        return _empty_bars(), pd.DataFrame(columns=["date", "close"])
    con = store.connect(market_db)
    try:
        bars = con.execute(
            "SELECT symbol, ts, open, high, low, close, volume FROM bars "
            "WHERE interval = '1m' ORDER BY symbol, ts"
        ).fetchdf()
        vix = con.execute(
            "SELECT CAST(ts AT TIME ZONE 'America/New_York' AS DATE) AS date, close "
            "FROM bars WHERE symbol = '^VIX' AND interval = '1d' ORDER BY ts"
        ).fetchdf()
    finally:
        con.close()
    return bars, vix


def _empty_bars() -> pd.DataFrame:
    return pd.DataFrame(columns=["symbol", "ts", "open", "high", "low", "close", "volume"])


def _write(con: duckdb.DuckDBPyConnection, schema: str, name: str, df: pd.DataFrame) -> None:
    con.register("_df", df)
    con.execute(f"CREATE OR REPLACE TABLE {schema}.{name} AS SELECT * FROM _df")
    con.unregister("_df")


def build_warehouse(
    dataset: str = "demo",
    db_path: Path | None = None,
    fills_path: Path | None = None,
    market_db: Path = store.DEFAULT_DB,
) -> BuildSummary:
    cfg = DATASETS[dataset]
    db_path = Path(db_path or cfg["db"])
    fills_path = Path(fills_path or cfg["fills"])

    result = ingest_file(fills_path)
    raw = pd.read_csv(fills_path, dtype=str, keep_default_na=False)
    bars, vix = _demo_market() if dataset == "demo" else _real_market(market_db)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        con.execute("SET TimeZone = 'UTC'")
        for schema in ("raw", "ingest"):
            con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        _write(con, "raw", "fills_raw", raw)
        _write(con, "raw", "bars_1m", bars)
        _write(con, "raw", "vix_daily", vix)
        _write(con, "ingest", "fills", result.fills)
        _write(con, "ingest", "trades", result.pairing.trades)
        _write(con, "ingest", "open_positions", result.pairing.open_positions)
        _write(
            con,
            "ingest",
            "quality_findings",
            pd.DataFrame(
                [
                    {
                        "check_name": f.check,
                        "severity": f.severity,
                        "n": f.count,
                        "message": f.message,
                        "examples": ", ".join(f.examples),
                    }
                    for f in result.report.findings
                ],
                columns=["check_name", "severity", "n", "message", "examples"],
            ),
        )
    finally:
        con.close()
    return BuildSummary(
        dataset, db_path, len(result.fills), len(result.pairing.trades), len(bars), len(vix), result
    )
