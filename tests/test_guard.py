import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "check_no_private", Path(__file__).parent.parent / "scripts" / "check_no_private.py"
)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def test_blocks_private_and_warehouse_files():
    paths = {"data/private/trades.csv", "data/warehouse/x.duckdb", "a.duckdb"}
    assert guard.violations(paths) == sorted(paths)


def test_blocks_stray_csv_but_allows_demo_and_fixtures():
    assert guard.violations({"export.csv"}) == ["export.csv"]
    assert guard.violations({"data/demo/trades.csv", "tests/fixtures/a.csv"}) == []
    assert guard.violations({"dbt_project/seeds/instruments.csv"}) == []


def test_allows_gitkeep_and_code():
    assert guard.violations({"data/private/.gitkeep", "src/trading_analytics/__init__.py"}) == []


def test_exactly_one_database_may_be_committed():
    assert guard.violations({"data/demo/demo.duckdb"}) == []
    for p in (
        "data/warehouse/demo.duckdb",
        "data/warehouse/private.duckdb",
        "demo.duckdb",
        "data/demo/other.duckdb",
        "data/demo/demo.duckdb.wal",
        "x/market.duckdb",
        "data/demo/private.duckdb",
        "backup.sqlite",
    ):
        assert guard.violations({p}) == [p], p


def test_any_data_file_with_private_in_its_path_is_blocked_even_in_demo_folders():
    for p in (
        "data/demo/private_Fills.csv",
        "tests/fixtures/my_private_export.csv",
        "dbt_project/seeds/private.csv",
        "data/demo/Private/trades.parquet",
    ):
        assert guard.violations({p}) == [p], p
    assert guard.violations({"data/demo/bars_1m.parquet", "data/demo/Fills.csv"}) == []


def test_parquet_outside_the_demo_folder_is_blocked():
    assert guard.violations({"bars.parquet"}) == ["bars.parquet"]


def test_the_guard_script_itself_and_docs_are_not_data_files():
    assert guard.violations({"scripts/check_no_private.py", "docs/expected.example.yaml"}) == []
