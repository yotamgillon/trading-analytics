"""Run: make reconcile. Loads the private fills export, builds trades, compares to expected.yaml.

Exits 0 on match, 1 on mismatch, 2 if an input file is missing/invalid. Never prints account ids.
"""

import sys
from pathlib import Path

from trading_analytics.ingest.reconcile import reconcile

FILLS = Path("data/private/Fills.csv")
EXPECTED = Path("data/private/expected.yaml")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    fills, expected = (Path(args[0]), Path(args[1])) if len(args) == 2 else (FILLS, EXPECTED)
    for p in (fills, expected):
        if not p.exists():
            print(f"Missing input file: {p}")
            return 2
    report, ok = reconcile(fills, expected)
    print(report)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
