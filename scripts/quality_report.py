"""Run: make quality (clean demo) | make quality-demo (demo + injected defects, writes the doc).

Prints the data quality report for a raw export. With --inject-defects the demo export is
corrupted first so the report shows what each check catches (written to docs/ for the README).
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

from trading_analytics.demo.defects import inject_defects
from trading_analytics.quality.pipeline import ingest_frame


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default="data/demo/Fills.csv")
    ap.add_argument("--inject-defects", action="store_true")
    ap.add_argument("--write", help="also write the Markdown report to this file")
    args = ap.parse_args(argv)

    raw = pd.read_csv(args.path, dtype=str, keep_default_na=False)
    if args.inject_defects:
        raw, _ = inject_defects(raw)
    result = ingest_frame(raw)
    print(result.report.render())
    if args.write:
        title = "Sample data quality report (demo data with deliberately injected defects)\n\n"
        Path(args.write).write_text(
            title + result.report.render(markdown=True)
            if args.inject_defects
            else result.report.render(markdown=True)
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
