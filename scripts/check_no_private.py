"""Fail if real trade data (or anything derived from it) is tracked or staged in git.

Allowed, because they are synthetic or reference data:
- data/private/.gitkeep and data/warehouse/.gitkeep (placeholders);
- CSV/XLSX/parquet under data/demo/, CSVs under tests/fixtures/ and dbt_project/seeds/;
- exactly ONE database file: data/demo/demo.duckdb (its contents are checked by
  tests/test_demo_db.py: nothing in it may come from outside data/demo/).
Everything else under data/private/ or data/warehouse/, every other .duckdb/.wal, and any data
file with "private" in its path is blocked.
"""

import subprocess
import sys

DEMO_DB = "data/demo/demo.duckdb"
ALLOWED_DATA_PREFIXES = ("data/demo/", "tests/fixtures/", "dbt_project/seeds/")
BLOCKED_PREFIXES = ("data/private/", "data/warehouse/")
ALLOWED_FILES = {"data/private/.gitkeep", "data/warehouse/.gitkeep", DEMO_DB}
DATA_SUFFIXES = (".csv", ".xlsx", ".xls", ".parquet", ".duckdb", ".wal", ".db", ".sqlite")


def git_paths() -> set[str]:
    tracked = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True
    ).stdout.splitlines()
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"], capture_output=True, text=True, check=True
    ).stdout.splitlines()
    return set(tracked) | set(staged)


def violations(paths: set[str]) -> list[str]:
    bad = []
    for p in sorted(paths):
        low = p.lower()
        if p in ALLOWED_FILES:
            continue
        is_data = low.endswith(DATA_SUFFIXES)
        if p.startswith(BLOCKED_PREFIXES):
            bad.append(p)
        elif is_data and "private" in low:
            bad.append(p)
        elif low.endswith((".duckdb", ".wal", ".db", ".sqlite")):
            bad.append(p)  # a database anywhere but the one allowed demo file
        elif is_data and not p.startswith(ALLOWED_DATA_PREFIXES):
            bad.append(p)
    return bad


def main() -> int:
    bad = violations(git_paths())
    if bad:
        print("Blocked: private/real data must not be committed:")
        for p in bad:
            print(f"  {p}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
