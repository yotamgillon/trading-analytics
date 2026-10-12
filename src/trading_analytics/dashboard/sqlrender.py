"""Run the REAL dbt mart SQL on filtered trades, so the dashboard never re-implements a metric.

The marts are Jinja SQL that use only three dbt features: ref(), var() and the macros in
dbt_project/macros/metrics.sql. We provide those three with a few lines of jinja2, point ref()
at filtered temp views, and execute the very same files the warehouse was built from. A date,
symbol or account filter therefore changes WHICH trades are aggregated, never HOW. (A test checks
that with no filter the output equals the dbt-built marts exactly.)
"""

from pathlib import Path

import duckdb
import jinja2

DBT = Path("dbt_project")
MART_ORDER = [  # dependency order
    "mart_equity_curve",
    "mart_streaks",
    "mart_kpis",
    "mart_perf_by_dimension",
    "mart_perf_hour_weekday",
    "mart_daily_performance",
]
PREFIX = "f_"


def _env(vars_: dict) -> jinja2.Environment:
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.globals["ref"] = lambda name: PREFIX + name
    env.globals["var"] = lambda name, default=None: vars_.get(name, default)
    return env


def render_model(name: str, vars_: dict, dbt_dir: Path = DBT) -> str:
    macros = (dbt_dir / "macros" / "metrics.sql").read_text()
    sql = (dbt_dir / "models" / "marts" / f"{name}.sql").read_text()
    return _env(vars_).from_string(macros + "\n" + sql).render()


def build_filtered_marts(
    con: duckdb.DuckDBPyConnection,
    where: str,
    params: list,
    start_balance: float = 0.0,
    combine_accounts: bool = False,
    dbt_dir: Path = DBT,
) -> dict:
    """Create temp views f_<mart> over trades matching `where`; return them as DataFrames."""
    vars_ = {"start_balance": start_balance, "win_loss_basis": "gross"}
    select = "* REPLACE ('All accounts' AS account)" if combine_accounts else "*"
    con.execute(
        f"CREATE OR REPLACE TEMP TABLE {PREFIX}fct_trades_enriched AS "
        f"SELECT {select} FROM marts.fct_trades_enriched WHERE {where}",
        params,
    )
    out = {"fct_trades_enriched": con.execute(f"SELECT * FROM {PREFIX}fct_trades_enriched").df()}
    for name in MART_ORDER:
        sql = render_model(name, vars_, dbt_dir)
        con.execute(f"CREATE OR REPLACE TEMP TABLE {PREFIX}{name} AS {sql}")
        out[name] = con.execute(f"SELECT * FROM {PREFIX}{name}").df()
    return out
