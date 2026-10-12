"""Loader for the private reconciliation file data/private/expected.yaml.

The file holds the totals your platform dashboard shows. It is gitignored; committed tests only
use synthetic files. The comparison itself arrives in Phase 2 (it needs trades).

Basis per metric mirrors how Lucid reports them: net_pnl is NET of commissions, avg_win/avg_loss
are GROSS. Win/loss classification (gross vs net) is configurable, default gross.
"""

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

METRIC_KEYS = {"net_pnl", "trades", "win_rate", "avg_win", "avg_loss"}


class ExpectedFileError(ValueError):
    pass


@dataclass(frozen=True)
class Expected:
    tolerance: float = 0.01
    win_loss_basis: str = "gross"  # how a trade is classified as win/loss: "gross" or "net"
    net_pnl_total: float | None = None
    trade_count_total: int | None = None
    by_day: dict[date, dict[str, float]] = field(default_factory=dict)
    by_symbol: dict[str, dict[str, float]] = field(default_factory=dict)


def _metrics(where: str, d: Any) -> dict[str, float]:
    if not isinstance(d, dict):
        raise ExpectedFileError(f"{where}: expected a mapping of metrics")
    unknown = set(d) - METRIC_KEYS
    if unknown:
        raise ExpectedFileError(f"{where}: unknown metric(s) {sorted(unknown)}")
    out = {k: float(v) for k, v in d.items()}
    if "win_rate" in out and not 0 <= out["win_rate"] <= 1:
        raise ExpectedFileError(f"{where}: win_rate must be a fraction between 0 and 1")
    return out


def load_expected(path: str | Path) -> Expected:
    data = yaml.safe_load(Path(path).read_text()) or {}
    if not isinstance(data, dict):
        raise ExpectedFileError("expected.yaml must be a mapping")
    unknown = set(data) - {
        "settings",
        "net_pnl_total",
        "trade_count_total",
        "by_day",
        "by_symbol",
    }
    if unknown:
        raise ExpectedFileError(f"Unknown top-level key(s): {sorted(unknown)}")

    settings = data.get("settings") or {}
    basis = settings.get("win_loss_basis", "gross")
    if basis not in ("gross", "net"):
        raise ExpectedFileError("settings.win_loss_basis must be 'gross' or 'net'")

    by_day: dict[date, dict[str, float]] = {}
    for k, v in (data.get("by_day") or {}).items():
        try:
            day = k if isinstance(k, date) else date.fromisoformat(str(k))
        except ValueError:
            raise ExpectedFileError(f"by_day key {k!r} is not an ISO date") from None
        by_day[day] = _metrics(f"by_day[{day}]", v)

    by_symbol = {
        str(k): _metrics(f"by_symbol[{k}]", v) for k, v in (data.get("by_symbol") or {}).items()
    }

    total_trades = data.get("trade_count_total")
    return Expected(
        tolerance=float(settings.get("tolerance", 0.01)),
        win_loss_basis=basis,
        net_pnl_total=None if data.get("net_pnl_total") is None else float(data["net_pnl_total"]),
        trade_count_total=None if total_trades is None else int(total_trades),
        by_day=by_day,
        by_symbol=by_symbol,
    )
