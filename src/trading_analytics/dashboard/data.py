"""Warehouse access for the dashboard: locate/build databases, list filters, run filtered marts."""

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from trading_analytics.dashboard.sqlrender import build_filtered_marts

REPO_ROOT = Path(__file__).resolve().parents[3]
# The deployed demo reads a PREBUILT synthetic database that is committed to the repo, so it needs
# neither dbt nor Yahoo at runtime. `make demo-db` rebuilds it; a test proves it contains nothing
# but data derived from data/demo/.
PREBUILT_DEMO_DB = REPO_ROOT / "data" / "demo" / "demo.duckdb"
LOCAL_DEMO_DB = REPO_ROOT / "data" / "warehouse" / "demo.duckdb"
# Explicit override (tests, or pointing the app at another demo build); None = automatic.
DEMO_DB: Path | None = (
    Path(os.environ["TRADING_DEMO_DB"]) if "TRADING_DEMO_DB" in os.environ else None
)
PRIVATE_DB = Path(os.environ.get("TRADING_PRIVATE_DB", REPO_ROOT / "data/warehouse/private.duckdb"))


def ensure_demo_warehouse(db: Path | None = None) -> Path:
    """Demo database to use: explicit > committed prebuilt > local build (dbt needed, fallback)."""
    db = db or DEMO_DB
    if db is None:
        if PREBUILT_DEMO_DB.exists():
            return PREBUILT_DEMO_DB
        db = LOCAL_DEMO_DB
    if db.exists():
        return db
    try:
        from trading_analytics.dbt_runner import run_dbt
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("demo database missing and dbt is not installed") from exc
    from trading_analytics.warehouse import build_warehouse

    build_warehouse("demo", db_path=db)
    if run_dbt(db, quiet=True) != 0:
        raise RuntimeError(
            "demo database is missing and building it failed; install the pipeline extra "
            "(`uv sync --all-extras`) or run `make demo-db`"
        )
    return db


def has_marts(db: Path) -> bool:
    if not db.exists():
        return False
    con = duckdb.connect(str(db), read_only=True)
    try:
        return bool(
            con.execute(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = 'marts' AND table_name = 'fct_trades_enriched'"
            ).fetchone()[0]
        )
    finally:
        con.close()


@dataclass
class FilterOptions:
    min_date: date
    max_date: date
    symbols: list[str]
    accounts: list[str]


def filter_options(db: Path) -> FilterOptions | None:
    con = duckdb.connect(str(db), read_only=True)
    try:
        lo, hi = con.execute(
            "SELECT min(trade_date), max(trade_date) FROM marts.fct_trades_enriched"
        ).fetchone()
        if lo is None:
            return None
        symbols = [
            r[0]
            for r in con.execute(
                "SELECT DISTINCT symbol FROM marts.fct_trades_enriched ORDER BY 1"
            ).fetchall()
        ]
        accounts = [
            r[0]
            for r in con.execute(
                "SELECT DISTINCT account FROM marts.fct_trades_enriched ORDER BY 1"
            ).fetchall()
        ]
    finally:
        con.close()
    return FilterOptions(pd.Timestamp(lo).date(), pd.Timestamp(hi).date(), symbols, accounts)


def mask_accounts(accounts: list[str]) -> dict[str, str]:
    """Real account name -> 'Account A', 'Account B' (safe for screenshots)."""
    return {a: f"Account {chr(65 + i)}" for i, a in enumerate(accounts)}


def compute(
    db: Path,
    start: date,
    end: date,
    symbols: tuple[str, ...],
    accounts: tuple[str, ...],
    start_balance: float = 0.0,
    combine_accounts: bool = True,
) -> dict:
    """Run the real mart SQL on the filtered trades; plus quality and context tables."""
    con = duckdb.connect(str(db), read_only=True)
    try:
        con.execute("SET TimeZone = 'UTC'")
        sym = ",".join("?" * len(symbols)) or "NULL"
        acc = ",".join("?" * len(accounts)) or "NULL"
        where = f"trade_date BETWEEN ? AND ? AND symbol IN ({sym}) AND account IN ({acc})"
        params = [start, end, *symbols, *accounts]
        marts = build_filtered_marts(con, where, params, start_balance, combine_accounts)
        marts["quality_findings"] = con.execute("SELECT * FROM ingest.quality_findings").df()
        return marts
    finally:
        con.close()
