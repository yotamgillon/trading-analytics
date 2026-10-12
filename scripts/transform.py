"""Run: make ingest | make transform  (DATASET=demo|private, default demo).

ingest    Python: clean + pair fills, load raw/ingest schemas into data/warehouse/<dataset>.duckdb
transform dbt: build and test staging -> intermediate models in that database
Both print only aggregates. Private data stays in the gitignored warehouse.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

import duckdb

from trading_analytics.warehouse import DATASETS, build_warehouse


def ingest(dataset: str) -> int:
    s = build_warehouse(dataset)
    print(
        f"[{dataset}] {s.db_path}: {s.n_fills} fills -> {s.n_trades} trades, "
        f"{s.n_bars} bars, {s.n_vix} VIX days"
    )
    print(s.ingest.report.render())
    return 0


def run_dbt(db: Path, quiet: bool = False) -> int:
    """`dbt build` (models + tests) against one DuckDB file; run from the repo root."""
    dbt = Path(sys.executable).parent / "dbt"
    cmd = [str(dbt) if dbt.exists() else "dbt", "build", "--project-dir", "dbt_project"]
    cmd += ["--profiles-dir", "dbt_project"]
    out = subprocess.DEVNULL if quiet else None
    return subprocess.run(
        cmd, env={**os.environ, "DBT_DUCKDB_PATH": str(db)}, stdout=out
    ).returncode


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
