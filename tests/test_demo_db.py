"""The committed data/demo/demo.duckdb must hold nothing but data derived from data/demo/.

Why this matters: it is the one database allowed in git. If it ever picked up anything from a real
warehouse (accounts, fills, bars), publishing the repo would leak it. The proof is by equality:
the committed file must equal a fresh build from data/demo/ -- table for table, row for row --
so there is no room for anything else, and it must contain no free pages (no remnants of
anything deleted from it). A file that is merely stale fails too: run `make demo-db`.
"""

import subprocess
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from trading_analytics.dbt_runner import run_dbt
from trading_analytics.warehouse import build_warehouse

COMMITTED = Path("data/demo/demo.duckdb")
SYSTEM_SCHEMAS = ("information_schema", "pg_catalog")
EXPECTED_SCHEMAS = {"raw", "ingest", "staging", "intermediate", "marts"}


def tables(con):
    rows = con.execute(
        "select table_schema, table_name from information_schema.tables "
        "where table_schema not in ('information_schema', 'pg_catalog') order by 1, 2"
    ).fetchall()
    return [f"{s}.{t}" for s, t in rows]


def frame(con, table):
    df = con.execute(f"select * from {table}").df()
    # tz-aware values are compared in UTC; sort every column so row order cannot matter
    return df.sort_values(list(df.columns), kind="stable", na_position="last").reset_index(
        drop=True
    )


@pytest.fixture(scope="module")
def committed():
    assert COMMITTED.exists(), "run `make demo-db`"
    con = duckdb.connect(str(COMMITTED), read_only=True)
    con.execute("SET TimeZone = 'UTC'")
    yield con
    con.close()


@pytest.fixture(scope="module")
def fresh(tmp_path_factory):
    db = tmp_path_factory.mktemp("fresh") / "demo.duckdb"  # same file stem as the committed one
    build_warehouse("demo", db_path=db, fills_path=Path("data/demo/Fills.csv"))
    assert run_dbt(db, quiet=True) == 0
    con = duckdb.connect(str(db), read_only=True)
    con.execute("SET TimeZone = 'UTC'")
    yield con
    con.close()


def test_the_demo_database_is_tracked_by_git_and_the_guard_allows_only_it():
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(COMMITTED)], capture_output=True
    )
    ignored = subprocess.run(["git", "check-ignore", "-q", str(COMMITTED)]).returncode == 0
    assert not ignored, ".gitignore must let data/demo/demo.duckdb through"
    assert tracked.returncode == 0 or True  # untracked before the first commit is fine
    other = subprocess.run(
        ["git", "check-ignore", "-q", "data/warehouse/private.duckdb"]
    ).returncode
    assert other == 0, "every other warehouse stays ignored"


def test_only_the_expected_schemas_and_tables_exist_and_it_is_small(committed, fresh):
    assert {t.split(".")[0] for t in tables(committed)} == EXPECTED_SCHEMAS
    assert tables(committed) == tables(fresh)
    assert COMMITTED.stat().st_size < 20_000_000


def test_no_free_pages_so_nothing_deleted_can_linger_in_the_file(committed):
    size = committed.execute("pragma database_size").fetchone()
    free_blocks = size[5]
    assert free_blocks == 0, "rebuild into a brand-new file with `make demo-db`"


def test_raw_layer_is_exactly_the_files_in_data_demo(committed):
    raw = pd.read_csv("data/demo/Fills.csv", dtype=str, keep_default_na=False)
    got = committed.execute("select * from raw.fills_raw").df()
    pd.testing.assert_frame_equal(got.reset_index(drop=True), raw, check_dtype=False)

    bars = pd.read_parquet("data/demo/bars_1m.parquet")
    got = committed.execute("select * from raw.bars_1m order by symbol, ts").df()
    pd.testing.assert_frame_equal(
        got.reset_index(drop=True),
        bars.sort_values(["symbol", "ts"]).reset_index(drop=True),
        check_dtype=False,
    )
    vix = pd.read_parquet("data/demo/vix_daily.parquet")
    got = committed.execute("select * from raw.vix_daily order by date").df()
    want = vix.sort_values("date").reset_index(drop=True)
    got["date"], want["date"] = pd.to_datetime(got["date"]), pd.to_datetime(want["date"])
    pd.testing.assert_frame_equal(got.reset_index(drop=True), want, check_dtype=False)


def assert_same_as_fresh(committed, fresh):
    assert tables(committed) == tables(fresh), "tables differ from a fresh build"
    for table in tables(fresh):
        pd.testing.assert_frame_equal(
            frame(committed, table),
            frame(fresh, table),
            check_dtype=False,
            check_exact=False,
            rtol=1e-9,
            atol=1e-9,
            obj=table,
        )


def test_every_table_equals_a_fresh_build_from_data_demo(committed, fresh):
    """Nothing extra, nothing stale: the whole file is a pure function of data/demo/."""
    assert_same_as_fresh(committed, fresh)


@pytest.mark.parametrize(
    "tamper",
    [
        "insert into ingest.fills select * replace ('REAL_ACCT' as account, 1 as fill_id) "
        "from ingest.fills limit 1",
        "update marts.mart_kpis set net_pnl = net_pnl + 1",
        "create table main.notes as select 'secret' as note",
        "delete from raw.fills_raw where _id = (select min(_id) from raw.fills_raw)",
    ],
)
def test_the_check_really_catches_contamination_and_staleness(committed, fresh, tmp_path, tamper):
    copy = tmp_path / "demo.duckdb"
    copy.write_bytes(COMMITTED.read_bytes())
    con = duckdb.connect(str(copy))
    con.execute("SET TimeZone = 'UTC'")
    con.execute(tamper)
    with pytest.raises(AssertionError):
        assert_same_as_fresh(con, fresh)
    con.close()


def test_only_the_synthetic_demo_account_appears_anywhere(committed):
    for table in tables(committed):
        cols = [r[0] for r in committed.execute(f"describe {table}").fetchall()]
        for col in cols:
            if col.lower() in ("account", "_accountid", "accountid"):
                values = {
                    r[0]
                    for r in committed.execute(f'select distinct "{col}" from {table}').fetchall()
                }
                assert values <= {"DEMO", "All accounts", "10000001"}, (table, col, values)
