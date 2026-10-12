"""Fills -> trades. A trade is a flat-to-flat position per (account, contract).

FIFO lots decide which entry price each exit is matched against. The sum of gross P&L over a
full flat-to-flat trade is independent of the costing method; FIFO only matters for per-lot
attribution and for the remaining lots of a position that is still open.
"""

from collections import deque
from dataclasses import dataclass, field

import pandas as pd

from trading_analytics.ingest.schema import TRADE_COLUMNS

OPEN_COLUMNS = [
    "account",
    "symbol",
    "contract",
    "side",
    "open_qty",
    "avg_entry_price",
    "since",
    "n_fills",
    "realized_gross_pnl",
]


@dataclass
class PairingResult:
    trades: pd.DataFrame
    open_positions: pd.DataFrame  # unmatched at end of data: no exit is invented
    inactive_fills: pd.DataFrame  # excluded from pairing, listed in the data quality report


@dataclass
class _Trade:
    direction: int  # +1 long, -1 short
    entry_time: pd.Timestamp
    first_fill_id: int
    qty_in: int = 0
    notional_in: float = 0.0
    qty_out: int = 0
    notional_out: float = 0.0
    gross: float = 0.0
    commissions: float = 0.0
    fees: float = 0.0
    peak: int = 0
    fill_ids: set[int] = field(default_factory=set)


def _match_group(g: pd.DataFrame) -> tuple[list[dict], dict | None]:
    first = g.iloc[0]
    account, symbol, contract = first["account"], first["symbol"], first["contract"]
    multiplier = float(first["multiplier"])

    pos = 0
    lots: deque[list[float]] = deque()  # [qty, price], oldest first
    cur: _Trade | None = None
    trades: list[dict] = []

    for f in g.itertuples(index=False):
        sign = 1 if f.side == "Buy" else -1
        remaining = int(f.qty)
        while remaining > 0:
            opening = pos == 0 or (pos > 0) == (sign > 0)
            part = remaining if opening else min(remaining, abs(pos))
            share = part / f.qty  # commission/fees split pro rata across the split parts

            if opening:
                if cur is None:
                    cur = _Trade(direction=sign, entry_time=f.fill_time, first_fill_id=f.fill_id)
                lots.append([part, f.price])
                cur.qty_in += part
                cur.notional_in += part * f.price
            else:
                need = part
                while need:
                    lot = lots[0]
                    m = min(need, lot[0])
                    cur.gross += cur.direction * (f.price - lot[1]) * m * multiplier
                    lot[0] -= m
                    need -= m
                    if lot[0] == 0:
                        lots.popleft()
                cur.qty_out += part
                cur.notional_out += part * f.price

            cur.commissions += f.commission * share
            cur.fees += f.fees * share
            cur.fill_ids.add(f.fill_id)
            pos += sign * part
            cur.peak = max(cur.peak, abs(pos))
            remaining -= part

            if pos == 0:
                trades.append(
                    {
                        "trade_id": f"{contract}-{cur.first_fill_id}",
                        "account": account,
                        "symbol": symbol,
                        "contract": contract,
                        "side": "Long" if cur.direction > 0 else "Short",
                        "qty": cur.qty_in,
                        "entry_time": cur.entry_time,
                        "exit_time": f.fill_time,
                        "trade_date": f.trade_date,
                        "entry_price": cur.notional_in / cur.qty_in,
                        "exit_price": cur.notional_out / cur.qty_out,
                        "gross_pnl": cur.gross,
                        "fees": cur.fees,
                        "commissions": cur.commissions,
                        "net_pnl": cur.gross - cur.fees - cur.commissions,
                        "n_fills": len(cur.fill_ids),
                        "max_position": cur.peak,
                    }
                )
                cur = None

    open_pos = None
    if cur is not None:
        open_qty = sum(q for q, _ in lots)
        open_pos = {
            "account": account,
            "symbol": symbol,
            "contract": contract,
            "side": "Long" if cur.direction > 0 else "Short",
            "open_qty": int(open_qty),
            "avg_entry_price": sum(q * p for q, p in lots) / open_qty,
            "since": cur.entry_time,
            "n_fills": len(cur.fill_ids),
            "realized_gross_pnl": cur.gross,
        }
    return trades, open_pos


def match_fills(fills: pd.DataFrame) -> PairingResult:
    inactive = fills[~fills["is_active"]].reset_index(drop=True)
    active = fills[fills["is_active"]]

    all_trades: list[dict] = []
    open_rows: list[dict] = []
    for _, g in active.groupby(["account", "contract"], sort=False):
        g = g.sort_values(["fill_time", "fill_id"], kind="stable")
        trades, open_pos = _match_group(g)
        all_trades.extend(trades)
        if open_pos:
            open_rows.append(open_pos)

    trades_df = pd.DataFrame(all_trades, columns=TRADE_COLUMNS)
    if not trades_df.empty:
        trades_df = trades_df.sort_values(["exit_time", "trade_id"]).reset_index(drop=True)
    return PairingResult(
        trades=trades_df,
        open_positions=pd.DataFrame(open_rows, columns=OPEN_COLUMNS),
        inactive_fills=inactive,
    )
