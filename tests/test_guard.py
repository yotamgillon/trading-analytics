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


def test_allows_gitkeep_and_code():
    assert guard.violations({"data/private/.gitkeep", "src/trading_analytics/__init__.py"}) == []
