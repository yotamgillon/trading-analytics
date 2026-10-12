"""Fail if real trade data is tracked or staged in git.

Allowed: data/private/.gitkeep, CSVs under data/demo/, tests/fixtures/ (synthetic only) and
dbt_project/seeds/ (reference tables such as contract multipliers, not trades).
"""

import subprocess
import sys

ALLOWED_CSV_PREFIXES = ("data/demo/", "tests/fixtures/", "dbt_project/seeds/")
BLOCKED_PREFIXES = ("data/private/", "data/warehouse/")
ALLOWED_FILES = {"data/private/.gitkeep", "data/warehouse/.gitkeep"}


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
        if p in ALLOWED_FILES:
            continue
        if p.startswith(BLOCKED_PREFIXES) or p.endswith((".duckdb", ".duckdb.wal")):
            bad.append(p)
        elif p.lower().endswith((".csv", ".xlsx")) and not p.startswith(ALLOWED_CSV_PREFIXES):
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
