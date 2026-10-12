"""Tradovate 'Fills.csv' export (as used via Lucid Trading).

Facts verified against a real export (see CLAUDE.md for privacy rules):
- `_`-prefixed columns are the raw API values; the display columns mirror them.
- `_timestamp` is UTC (trailing Z). The display `Timestamp` is local time and shifts with DST,
  so it is ignored.
- `B/S` carries a leading space (" Buy"); it is stripped before cross-checking.
- `commission` is the total for the fill. The export has no fees column, so fees = 0.
- One order may produce several fills sharing the same Order ID (partial fills).
"""

import warnings
from typing import ClassVar

import pandas as pd

from trading_analytics.ingest.instruments import get_instrument
from trading_analytics.ingest.schema import FILL_COLUMNS, SchemaError, validate_fills
from trading_analytics.quality.findings import Finding, examples_of
from trading_analytics.quality.timezone import to_israel

SOURCE = "tradovate_fills"
_ACTION_TO_SIDE = {"0": "Buy", "1": "Sell"}
_BOOL = {"true": True, "false": False}


class InactiveFillsWarning(UserWarning):
    pass


class TradovateFillsAdapter:
    name: ClassVar[str] = SOURCE
    signature: ClassVar[frozenset[str]] = frozenset({"_orderId", "Fill ID", "_timestamp"})
    required_columns: ClassVar[tuple[str, ...]] = (
        "_id",
        "_orderId",
        "_timestamp",
        "_tradeDate",
        "_action",
        "_qty",
        "_price",
        "_active",
        "Account",
        "Contract",
        "Product",
        "commission",
    )
    id_column: ClassVar[str] = "_id"

    def raw_checks(self, raw: pd.DataFrame) -> list[Finding]:
        """The display `Timestamp` (Israel local, DST-aware) must equal UTC converted to Israel.

        We never use the display column, but a mismatch means the export's clock or our UTC
        parsing is off, which would silently shift every hour/session bucket.
        """
        raw = raw.rename(columns=str.strip)
        utc = pd.to_datetime(raw["_timestamp"], utc=True, format="ISO8601")
        expected = to_israel(utc).dt.strftime("%m/%d/%Y %H:%M:%S")
        bad = expected != raw["Timestamp"].str.strip()
        if not bad.any():
            return []
        return [
            Finding(
                "display_time_mismatch",
                "warning",
                int(bad.sum()),
                "platform display time differs from UTC converted to Israel time (kept; UTC is "
                "the source of truth)",
                examples_of(raw.loc[bad, "_id"]),
            )
        ]

    def parse(self, raw: pd.DataFrame) -> pd.DataFrame:
        raw = raw.rename(columns=str.strip)
        if raw.empty:
            raise SchemaError("Fills export contains no rows")

        side = raw["_action"].str.strip().map(_ACTION_TO_SIDE)
        if side.isna().any():
            raise SchemaError(f"Unexpected _action values: {sorted(set(raw['_action']))}")

        # Cross-check raw API columns against their display twins: catches corrupted exports.
        if (side != raw["B/S"].str.strip()).any():
            raise SchemaError("_action disagrees with B/S column")
        if (raw["_qty"].astype(int) != raw["Quantity"].astype(int)).any():
            raise SchemaError("_qty disagrees with Quantity column")
        if ((raw["_price"].astype(float) - raw["Price"].astype(float)).abs() > 1e-9).any():
            raise SchemaError("_price disagrees with Price column")

        is_active = raw["_active"].str.strip().str.lower().map(_BOOL)
        if is_active.isna().any():
            raise SchemaError(f"Unexpected _active values: {sorted(set(raw['_active']))}")

        symbol = raw["Product"].str.strip()
        multiplier = symbol.map(lambda s: get_instrument(s).multiplier)  # fails on unknown

        fills = pd.DataFrame(
            {
                "fill_id": raw["_id"].astype("int64"),
                "order_id": raw["_orderId"].astype("int64"),
                "account": raw["Account"].str.strip(),
                "symbol": symbol,
                "contract": raw["Contract"].str.strip(),
                "side": side,
                "qty": raw["_qty"].astype("int64"),
                "price": raw["_price"].astype(float),
                "fill_time": pd.to_datetime(raw["_timestamp"], utc=True, format="ISO8601"),
                "trade_date": pd.to_datetime(raw["_tradeDate"]).dt.date,
                "commission": raw["commission"].astype(float),
                "fees": 0.0,
                "multiplier": multiplier.astype(float),
                "is_active": is_active.astype(bool),
                "source_format": SOURCE,
            }
        )[FILL_COLUMNS]

        n_inactive = int((~fills["is_active"]).sum())
        if n_inactive:
            warnings.warn(
                f"{n_inactive} inactive fill(s) found; they are kept here, excluded from "
                "pairing, and listed in the data quality report.",
                InactiveFillsWarning,
                stacklevel=2,
            )

        fills = fills.sort_values(["fill_time", "fill_id"], kind="stable").reset_index(drop=True)
        return validate_fills(fills)
