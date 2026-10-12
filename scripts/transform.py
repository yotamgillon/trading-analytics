"""Run: make ingest | make transform  (DATASET=demo|private, default demo).

ingest    Python: clean + pair fills, load raw/ingest schemas into data/warehouse/<dataset>.duckdb
transform dbt: build and test staging -> intermediate models in that database
Both print only aggregates. Private data stays in the gitignored warehouse.
"""

import argparse
import os
import sys

import duckdb

from trading_analytics.dbt_runner import run_dbt
from trading_analytics.warehouse import DATASETS, build_warehouse


def ingest(dataset: str) -> int:
    s = build_warehouse(dataset)
    print(
        f"[{dataset}] {s.db_path}: {s.n_fills} fills -> {s.n_trades} trades, "
        f"{s.n_bars} bars, {s.n_vix} VIX days"
    )
    print(s.ingest.report.render())
    return 0


def transform(dataset: str) -> int:
    db = DATASETS[dataset]["db"]
    if not db.exists():
        print(f"{db} does not exist: run `make ingest DATASET={dataset}` first")
        return 2
    rc = run_dbt(db)
    if rc == 0:
        summarize(db)
    return rc


def summarize(db) -> None:
    con = duckdb.connect(str(db), read_only=True)
    try:
        rows = con.execute(
            "SELECT status, count(*) FROM intermediate.int_fill_bar_check GROUP BY 1 ORDER BY 1"
        ).fetchall()
        basis = con.execute(
            "SELECT mae_mfe_basis, count(*) FROM intermediate.int_trade_context "
            "GROUP BY 1 ORDER BY 1"
        ).fetchall()
    finally:
        con.close()
    print("\nFill-vs-bar price check (tolerance in dbt_project.yml):", dict(rows))
    print("MAE/MFE basis (trades):", dict(basis))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["ingest", "transform"])
    ap.add_argument("--dataset", default=os.environ.get("DATASET", "demo"), choices=DATASETS)
    args = ap.parse_args(argv)
    return ingest(args.dataset) if args.step == "ingest" else transform(args.dataset)


if __name__ == "__main__":
    sys.exit(main())
