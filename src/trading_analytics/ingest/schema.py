"""Canonical schemas. Every adapter must emit exactly FILL_COLUMNS; Phase 2 emits TRADE_COLUMNS."""

import pandas as pd

FILL_COLUMNS = [
    "fill_id",
    "order_id",
    "account",
    "symbol",
    "contract",
    "side",
    "qty",
    "price",
    "fill_time",  # tz-aware UTC
    "trade_date",  # exchange session date as reported by the platform
    "commission",  # total for the fill (not per contract)
    "fees",
    "multiplier",
    "is_active",
    "source_format",
]

# Produced by the fill matcher. gross_pnl/net_pnl are split explicitly because platforms report
# some metrics gross (avg win/loss) and others net (daily P&L).
TRADE_COLUMNS = [
    "trade_id",  # "<contract>-<first fill id>": unique, deterministic, contains no account id
    "account",
    "symbol",
    "contract",
    "side",  # Long / Short (direction of the opening fills)
    "qty",  # total contracts opened (entry quantity)
    "entry_time",  # first fill of the trade
    "exit_time",  # fill that took the position back to flat
    "trade_date",  # platform trade_date of the exit fill (how daily P&L is attributed)
    "entry_price",  # quantity-weighted average
    "exit_price",  # quantity-weighted average
    "gross_pnl",
    "fees",
    "commissions",
    "net_pnl",  # gross_pnl - fees - commissions
    "n_fills",  # distinct fills touching the trade (a flip fill counts in both trades)
    "max_position",  # peak open contracts during the trade
]


class SchemaError(ValueError):
    pass


def validate_fills(df: pd.DataFrame) -> pd.DataFrame:
    """Raise SchemaError on any violation; return df unchanged otherwise."""
    if list(df.columns) != FILL_COLUMNS:
        raise SchemaError(f"Fill columns {list(df.columns)} != canonical {FILL_COLUMNS}")
    if df.isna().any().any():
        bad = df.columns[df.isna().any()].tolist()
        raise SchemaError(f"Nulls in required columns: {bad}")
    if df["fill_id"].duplicated().any():
        raise SchemaError("Duplicate fill_id values")
    if not set(df["side"]) <= {"Buy", "Sell"}:
        raise SchemaError(f"Invalid side values: {sorted(set(df['side']))}")
    for col in ("qty", "price", "multiplier"):
        if (df[col] <= 0).any():
            raise SchemaError(f"Non-positive values in {col}")
    for col in ("commission", "fees"):
        if (df[col] < 0).any():
            raise SchemaError(f"Negative values in {col}")
    if str(df["fill_time"].dtype) != "datetime64[ns, UTC]" and "UTC" not in str(
        df["fill_time"].dtype
    ):
        raise SchemaError(f"fill_time must be tz-aware UTC, got {df['fill_time'].dtype}")
    return df
