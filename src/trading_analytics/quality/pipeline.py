"""raw CSV -> cleaned canonical fills -> trades, plus a report of everything that was changed."""

import warnings
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from trading_analytics.ingest.detect import detect_adapter
from trading_analytics.ingest.fill_matcher import PairingResult, match_fills
from trading_analytics.quality import checks
from trading_analytics.quality.findings import Finding, QualityReport, examples_of


@dataclass
class IngestResult:
    fills: pd.DataFrame  # cleaned canonical fills (inactive ones included, flagged)
    pairing: PairingResult
    quarantined: pd.DataFrame  # raw rows excluded for missing values (in memory only)
    report: QualityReport


def ingest_file(path: str | Path) -> IngestResult:
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    return ingest_frame(raw)


def ingest_frame(raw: pd.DataFrame) -> IngestResult:
    adapter = detect_adapter(raw.columns)()
    report = QualityReport(rows_raw=len(raw))

    raw_clean, quarantined, findings = checks.clean_raw(raw, adapter)
    for f in findings:
        report.add(f)
    for f in adapter.raw_checks(raw_clean):
        report.add(f)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # inactive fills are reported below, as a finding
        fills = adapter.parse(raw_clean)

    fills, removed, price_findings = checks.quarantine_bad_prices(fills)
    for f in price_findings:
        report.add(f)
    excluded = set(removed["contract"]) | {
        c.strip() for c in quarantined.get("Contract", []) if c.strip()
    }
    report.add(checks.desync_warning(excluded))
    for f in checks.warn_checks(fills):
        report.add(f)
    report.rows_clean = len(fills)

    pairing = match_fills(fills)
    inactive = pairing.inactive_fills
    report.add(
        Finding(
            "inactive_fills",
            "fixed",
            len(inactive),
            "is_active=false fills excluded from pairing (meaning of the flag is unconfirmed)",
            examples_of(inactive["fill_id"]),
        )
    )
    opens = pairing.open_positions
    report.add(
        Finding(
            "unmatched_open_position",
            "warning",
            len(opens),
            "position still open at the end of the data; no exit invented, no trade created: "
            + "; ".join(
                f"{r.contract} {r.side} {r.open_qty} @ {r.avg_entry_price:.2f}"
                for r in opens.itertuples()
            ),
        )
    )
    report.add(
        Finding(
            "summary",
            "info",
            len(pairing.trades),
            f"{int(fills['is_active'].sum())} active fills paired into "
            f"{len(pairing.trades)} flat-to-flat trades",
        )
    )
    return IngestResult(fills, pairing, quarantined, report)
