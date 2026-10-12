"""Synthetic canonical fills for matcher tests (no platform parsing involved)."""

from datetime import date

import pandas as pd

from trading_analytics.ingest.schema import FILL_COLUMNS

MULT = {"NQ": 20.0, "MNQ": 2.0}


def fill(
    fill_id,
    minute,
    side,
    qty,
    price,
    *,
    commission=None,
    contract="NQH0",
    account="ACC",
    active=True,
    day=date(2030, 1, 7),
):
    symbol = contract.removesuffix("H0")
    return {
        "fill_id": fill_id,
        "order_id": fill_id,
        "account": account,
        "symbol": symbol,
        "contract": contract,
        "side": side,
        "qty": qty,
        "price": price,
        "fill_time": pd.Timestamp("2030-01-07 14:00", tz="UTC") + pd.Timedelta(minutes=minute),
        "trade_date": day,
        "commission": float(qty) if commission is None else commission,  # $1 per contract
        "fees": 0.0,
        "multiplier": MULT[symbol],
        "is_active": active,
        "source_format": "synthetic",
    }


def make_fills(*rows):
    return pd.DataFrame(list(rows), columns=FILL_COLUMNS)
