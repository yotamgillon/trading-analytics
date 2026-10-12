"""Run: make demo-db. Rebuild the PREBUILT synthetic demo database (data/demo/demo.duckdb).

This file is committed so the deployed demo needs neither dbt nor Yahoo at runtime. It is built
from data/demo/ ONLY, into a brand-new file (never an existing warehouse that might once have held
private data). tests/test_demo_db.py proves it holds nothing but data derived from data/demo/ and
that it is not stale. Rebuild whenever the demo data, the dbt models or the pairing logic change.
"""

import sys
from pathlib import Path

import duckdb

from trading_analytics.dbt_runner import run_dbt
from trading_analytics.warehouse import build_warehouse

OUT = Path("data/demo/demo.duckdb")


def main() -> int:
    for f in (OUT, OUT.with_name(OUT.name + ".wal")):
        f.unlink(missing_ok=True)  # fresh file: no pages from anything built before
    s = build_warehouse("demo", db_path=OUT, fills_path=Path("data/demo/Fills.csv"))
    if run_dbt(OUT, quiet=True) != 0:
        print("dbt build failed; demo.duckdb not usable")
        return 1
    con = duckdb.connect(str(OUT))
    con.execute("CHECKPOINT")
    con.close()
    print(
        f"{OUT}: {s.n_fills} fills, {s.n_trades} trades, {s.n_bars} bars, "
        f"{OUT.stat().st_size / 1e6:.1f} MB"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
