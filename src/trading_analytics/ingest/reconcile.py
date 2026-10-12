"""Compare computed trades against the totals the platform dashboard shows (expected.yaml).

Basis mirrors the platform: net_pnl is NET; avg_win / avg_loss are GROSS; win/loss classification
is gross by default (configurable). win_rate = winners / all trades (scratch trades count as
neither win nor loss). avg_loss is compared by absolute value so the sign convention of the
platform display does not matter. Nothing here prints account identifiers.
"""

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from trading_analytics.ingest.expected import Expected, load_expected
from trading_analytics.ingest.fill_matcher import PairingResult
from trading_analytics.quality.pipeline import ingest_file


@dataclass(frozen=True)
class Mismatch:
    scope: str
    metric: str
    expected: float
    actual: float | None

    def __str__(self) -> str:
        if self.actual is None:
            return (
                f"  {self.scope:<22} {self.metric:<9} expected {self.expected:>12.2f}  actual n/a"
            )
        diff = self.actual - self.expected
        return (
            f"  {self.scope:<22} {self.metric:<9} expected {self.expected:>12.2f}  "
            f"actual {self.actual:>12.2f}  diff {diff:>+10.2f}"
        )


def compute_metrics(trades: pd.DataFrame, basis: str = "gross") -> dict[str, float | None]:
    n = len(trades)
    wins = trades[trades[f"{basis}_pnl"] > 0]
    losses = trades[trades[f"{basis}_pnl"] < 0]
    return {
        "net_pnl": float(trades["net_pnl"].sum()),
        "trades": float(n),
        "win_rate": len(wins) / n if n else None,
        "avg_win": float(wins["gross_pnl"].mean()) if len(wins) else None,
        "avg_loss": abs(float(losses["gross_pnl"].mean())) if len(losses) else None,
    }


def _compare_scope(
    scope: str, expected: dict[str, float], trades: pd.DataFrame, exp: Expected
) -> list[Mismatch]:
    actual = compute_metrics(trades, exp.win_loss_basis)
    out = []
    for metric, want in expected.items():
        want = abs(want) if metric == "avg_loss" else want
        got = actual[metric]
        tol = 1e-4 if metric == "win_rate" else exp.tolerance
        if got is None or abs(got - want) > tol:
            out.append(Mismatch(scope, metric, want, got))
    return out


def compare(trades: pd.DataFrame, exp: Expected) -> list[Mismatch]:
    mismatches: list[Mismatch] = []
    totals = {}
    if exp.net_pnl_total is not None:
        totals["net_pnl"] = exp.net_pnl_total
    if exp.trade_count_total is not None:
        totals["trades"] = float(exp.trade_count_total)
    mismatches += _compare_scope("TOTAL", totals, trades, exp)
    for day, metrics in sorted(exp.by_day.items()):
        subset = trades[trades["trade_date"] == day]
        mismatches += _compare_scope(f"day {day}", metrics, subset, exp)
    for symbol, metrics in sorted(exp.by_symbol.items()):
        subset = trades[trades["symbol"] == symbol]
        mismatches += _compare_scope(f"symbol {symbol}", metrics, subset, exp)
    return mismatches


def pairing_report(fills: pd.DataFrame, result: PairingResult) -> str:
    lines = [
        f"Fills: {len(fills)} total, {int(fills['is_active'].sum())} active -> "
        f"{len(result.trades)} trades",
        f"Inactive fills excluded from pairing: {len(result.inactive_fills)}",
    ]
    for r in result.inactive_fills.itertuples():
        lines.append(f"  fill_id {r.fill_id} {r.contract} {r.side} {r.qty} @ {r.price}")
    lines.append(
        f"Open positions at end of data (unmatched, no exit invented): {len(result.open_positions)}"
    )
    for r in result.open_positions.itertuples():
        lines.append(
            f"  {r.contract} {r.side} {r.open_qty} @ avg {r.avg_entry_price:.2f} since {r.since}"
        )
    return "\n".join(lines)


def reconcile(fills_path: Path, expected_path: Path) -> tuple[str, bool]:
    ingested = ingest_file(fills_path)
    fills, result = ingested.fills, ingested.pairing
    exp = load_expected(expected_path)
    mismatches = compare(result.trades, exp)

    lines = [ingested.report.render(), "", pairing_report(fills, result), ""]
    covered = set(exp.by_day)
    extra_days = sorted(set(result.trades["trade_date"]) - covered) if exp.by_day else []
    if extra_days:
        lines.append(f"Note: {len(extra_days)} trade day(s) are not covered by expected.yaml.")
    if mismatches:
        lines.append(f"RECONCILIATION FAILED: {len(mismatches)} mismatch(es)")
        lines += [str(m) for m in mismatches]
    else:
        lines.append("RECONCILIATION OK: all expected values match.")
    return "\n".join(lines), not mismatches
