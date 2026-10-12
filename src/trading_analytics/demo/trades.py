"""Synthetic trader: generates raw Tradovate-format fills with NO edge.

Why there is provably no edge (the argument to defend in an interview):
- Prices are a driftless martingale (see market.py).
- Direction is a coin flip, size/symbol/timeout are drawn independently of price and time.
- Stops/targets are set from volatility known at entry, in volatility units, so win probability
  does not depend on the volatility level; exits happen at stop, target or a random timeout.
- Every scale-in/out happens at a *fixed random delay after entry* (a stopping time that does not
  look ahead). By optional stopping, any such rule has zero expected gross P&L.
- Trades are dropped by a uniform random subset (independent of outcomes).
So expected gross P&L is 0 in every hour / weekday / volatility regime. Net P&L is negative only
because of commissions, as for most real traders. Trade duration is outcome-coupled by
construction (a closer stop is hit sooner than a farther target); it is known only ex post, so
the no-edge tests cover ex-ante conditions only (hour, weekday, volatility regime, side, size).
"""

from dataclasses import dataclass, field
from datetime import date
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from trading_analytics.demo.market import RTH_OFFSET, TICK, DayBars, round_tick
from trading_analytics.ingest.instruments import get_instrument

ACCOUNT = "DEMO"
ACCOUNT_ID = "10000001"
COMMISSION_PER_CONTRACT = {"NQ": 1.75, "MNQ": 0.50}
LAST_ENTRY_IDX = RTH_OFFSET + 330  # 15:00 ET: keeps every trade (max 60 min) inside the bars
MAX_HOLD = 60
STOP_UNITS, TARGET_UNITS = 1.0, 1.5  # in units of u = 3 * trailing 1-min sigma
P_PARTIAL_ENTRY, P_PARTIAL_EXIT = 0.20, 0.15
P_SCALE_IN, P_SCALE_OUT, P_FLIP = 0.12, 0.12, 0.04
IL = ZoneInfo("Asia/Jerusalem")
RAW_HEADER = (
    "_id,_orderId,_contractId,_timestamp,_tradeDate,_action,_qty,_price,_active,_accountId,"
    "Fill ID,Order ID,Timestamp,Date,Account,B/S,Quantity,Price,_priceFormat,_priceFormatType,"
    "_tickSize,Contract,Product,Product Description,commission"
).split(",")
DESCRIPTIONS = {"NQ": "E-Mini NASDAQ 100", "MNQ": "Micro E-mini NASDAQ-100"}
QTY_CHOICES = {
    "NQ": ([1, 2, 3], [0.6, 0.3, 0.1]),
    "MNQ": ([1, 2, 3, 4, 5, 6, 8, 10], [0.2, 0.15, 0.15, 0.12, 0.12, 0.1, 0.08, 0.08]),
}


@dataclass
class _Order:
    ts: pd.Timestamp
    side: str  # "Buy" / "Sell"
    qty: int
    price: float
    partial: bool = False


@dataclass
class _Trade:
    day: date
    symbol: str
    contract: str
    direction: int
    sigma: float
    entry_ts: pd.Timestamp
    exit_ts: pd.Timestamp
    entry_orders: list[_Order] = field(default_factory=list)
    exit_orders: list[_Order] = field(default_factory=list)
    flip_from: "_Trade | None" = None  # previous trade whose exit is merged with our entry


def contract_for(day: date, symbol: str) -> str:
    code = "H6" if day <= date(2026, 3, 12) else "M6" if day <= date(2026, 6, 11) else "U6"
    return f"{symbol}{code}"


def _trailing_sigma(close: np.ndarray, i: int) -> float:
    window = np.diff(close[max(0, i - 30) : i + 1])
    return max(float(window.std()), 2 * TICK)


def _side(direction: int, opening: bool) -> str:
    return "Buy" if (direction > 0) == opening else "Sell"


def _simulate_trade(
    bars: DayBars,
    i: int,
    price: float,
    ts: pd.Timestamp,
    symbol: str,
    direction: int,
    rng: np.random.Generator,
    flip_from: "_Trade | None" = None,
) -> tuple[_Trade, int, float]:
    """Run one trade from bar i; return (trade, exit_bar_index, exit_price)."""
    choices, probs = QTY_CHOICES[symbol]
    qty = int(rng.choice(choices, p=probs))
    sigma = _trailing_sigma(bars.c, i)
    u = 3 * sigma
    stop = price - direction * float(round_tick(STOP_UNITS * u))
    target = price + direction * float(round_tick(TARGET_UNITS * u))
    timeout = int(np.clip(np.ceil(rng.exponential(9)), 1, MAX_HOLD))
    d_in = int(rng.integers(1, 15)) if rng.random() < P_SCALE_IN else None
    d_out = int(rng.integers(1, 15)) if qty >= 2 and rng.random() < P_SCALE_OUT else None
    partial_entry = qty >= 2 and rng.random() < P_PARTIAL_ENTRY
    partial_exit = rng.random() < P_PARTIAL_EXIT

    trade = _Trade(bars.day, symbol, contract_for(bars.day, symbol), direction, sigma, ts, ts)
    trade.entry_orders.append(_Order(ts, _side(direction, True), qty, price, partial_entry))
    pos = qty

    for j in range(i + 1, i + timeout + 1):
        hi, lo, cl = bars.h[j], bars.l[j], bars.c[j]
        hit_stop = lo <= stop if direction > 0 else hi >= stop
        hit_tgt = hi >= target if direction > 0 else lo <= target
        if hit_stop and hit_tgt:
            hit_stop, hit_tgt = (True, False) if rng.random() < 0.5 else (False, True)
        bar_start = bars.ts[j]
        if hit_stop or hit_tgt or j == i + timeout:
            exit_price = stop if hit_stop else target if hit_tgt else float(cl)
            offset = rng.uniform(5, 55) if (hit_stop or hit_tgt) else rng.uniform(55, 59.9)
            exit_ts = bar_start + pd.Timedelta(seconds=float(offset)).round("ms")
            trade.exit_orders.append(
                _Order(exit_ts, _side(direction, False), pos, exit_price, partial_exit and pos >= 2)
            )
            trade.exit_ts = exit_ts
            return trade, j, exit_price
        # no exit this bar: fixed-delay scale events (stopping times, no look-ahead)
        ev_ts = bar_start + pd.Timedelta(seconds=float(rng.uniform(20, 50))).round("ms")
        if j - i == d_in:
            add = max(1, qty // 2)
            trade.entry_orders.append(_Order(ev_ts, _side(direction, True), add, float(cl)))
            pos += add
        elif j - i == d_out and pos >= 2:
            cut = pos // 2
            trade.exit_orders.append(_Order(ev_ts, _side(direction, False), cut, float(cl)))
            pos -= cut
    raise AssertionError("unreachable: the last bar always exits")


def _entry_candidates(k: int, rng: np.random.Generator) -> list[int]:
    """Entry minutes: busy open, flat middle, some afternoon. Depends on time only."""
    n = RTH_OFFSET + 330
    idx = np.arange(RTH_OFFSET, n)
    w = 1.0 + 2.5 * np.exp(-(idx - RTH_OFFSET) / 60) + 0.6 * ((idx - RTH_OFFSET) > 270)
    return sorted(rng.choice(idx, size=k, replace=True, p=w / w.sum()).tolist())


def simulate_day(bars: DayBars, k: int, rng: np.random.Generator) -> list[_Trade]:
    trades: list[_Trade] = []
    free = RTH_OFFSET
    for cand in _entry_candidates(k, rng):
        i = max(cand, free)
        if i > LAST_ENTRY_IDX:
            break
        symbol = "NQ" if rng.random() < 0.3 else "MNQ"
        direction = 1 if rng.random() < 0.5 else -1
        ts = bars.ts[i] + pd.Timedelta(seconds=float(rng.uniform(55, 59.9))).round("ms")
        trade, j, px = _simulate_trade(bars, i, float(bars.c[i]), ts, symbol, direction, rng)
        trades.append(trade)
        while j <= LAST_ENTRY_IDX and rng.random() < P_FLIP:  # reversal at the exit price
            nxt, j, px = _simulate_trade(
                bars, j, px, trade.exit_ts, symbol, -trade.direction, rng, flip_from=trade
            )
            trades.append(nxt)
            trade = nxt
        free = j + 1 + int(rng.integers(0, 5))
    return trades


def generate_trades(days: list[DayBars], n_trades: int, rng: np.random.Generator) -> list[_Trade]:
    scale = 1.15
    while True:
        weights = rng.multinomial(int(n_trades * scale), np.full(len(days), 1 / len(days)))
        all_trades: list[_Trade] = []
        for bars, k in zip(days, weights, strict=True):
            all_trades.extend(simulate_day(bars, int(k), rng))
        if len(all_trades) >= n_trades:
            break
        scale *= 1.2
    keep = set(rng.choice(len(all_trades), n_trades, replace=False).tolist())  # outcome-blind
    kept = [t for i, t in enumerate(all_trades) if i in keep]
    kept_ids = {id(t) for t in kept}
    for t in kept:
        if t.flip_from is not None and id(t.flip_from) not in kept_ids:
            t.flip_from = None
    return kept


def _split(order: _Order, rng: np.random.Generator) -> list[tuple[pd.Timestamp, int]]:
    """Partial fills: same order, a few ms apart, quantities summing to the order quantity."""
    if not (order.partial and order.qty >= 2):
        return [(order.ts, order.qty)]
    parts = 3 if order.qty >= 4 and rng.random() < 0.3 else 2
    cuts = sorted(rng.choice(np.arange(1, order.qty), parts - 1, replace=False).tolist())
    qtys = np.diff([0, *cuts, order.qty]).tolist()
    t, out = order.ts, []
    for q in qtys:
        out.append((t, int(q)))
        t = t + pd.Timedelta(milliseconds=int(rng.integers(5, 150)))
    return out


def _format_ms(ts: pd.Timestamp) -> str:
    return ts.strftime("%Y-%m-%d %H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"


def build_raw_export(
    trades: list[_Trade], rng: np.random.Generator
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (raw Tradovate-format fills as strings, ground-truth trades)."""
    # Flat list of (order, trade) with flip exit+entry merged into one order.
    merged_into_next = {id(t.flip_from) for t in trades if t.flip_from is not None}
    orders: list[tuple[_Order, _Trade]] = []
    for t in trades:
        for o in t.entry_orders:
            if t.flip_from is not None and o is t.entry_orders[0]:
                continue  # represented by the previous trade's (merged) exit order
            orders.append((o, t))
        for o in t.exit_orders:
            if id(t) in merged_into_next and o is t.exit_orders[-1]:
                nxt = next(x for x in trades if x.flip_from is t)
                o = _Order(o.ts, o.side, o.qty + nxt.entry_orders[0].qty, o.price)
            orders.append((o, t))
    orders.sort(key=lambda p: p[0].ts)

    contracts = sorted({t.contract for t in trades})
    contract_id = {c: 3_000_001 + n for n, c in enumerate(contracts)}
    counter = iter(range(800_000_000_001, 900_000_000_000))
    rows = []
    for order, t in orders:
        order_id = next(counter)
        for ts, qty in _split(order, rng):
            fill_id = next(counter)
            local = ts.astimezone(IL)
            rows.append(
                {
                    "_id": fill_id,
                    "_orderId": order_id,
                    "_contractId": contract_id[t.contract],
                    "_timestamp": _format_ms(ts),
                    "_tradeDate": ts.tz_convert("America/New_York").date().isoformat(),
                    "_action": 0 if order.side == "Buy" else 1,
                    "_qty": qty,
                    "_price": order.price,
                    "_active": "true",
                    "_accountId": ACCOUNT_ID,
                    "Fill ID": fill_id,
                    "Order ID": order_id,
                    "Timestamp": local.strftime("%m/%d/%Y %H:%M:%S"),
                    "Date": f"{local.month}/{local.day}/{local.year % 100:02d}",
                    "Account": ACCOUNT,
                    "B/S": " " + order.side,
                    "Quantity": qty,
                    "Price": f"{order.price:.2f}",
                    "_priceFormat": -2,
                    "_priceFormatType": 0,
                    "_tickSize": TICK,
                    "Contract": t.contract,
                    "Product": t.symbol,
                    "Product Description": DESCRIPTIONS[t.symbol],
                    "commission": qty * COMMISSION_PER_CONTRACT[t.symbol],
                }
            )
    raw = pd.DataFrame(rows, columns=RAW_HEADER).astype(str)
    return raw, _ground_truth(trades)


def _ground_truth(trades: list[_Trade]) -> pd.DataFrame:
    """P&L computed independently of the matcher: sum(exit notional) - sum(entry notional)."""
    rows = []
    for t in trades:
        mult = get_instrument(t.symbol).multiplier
        rate = COMMISSION_PER_CONTRACT[t.symbol]
        q_in = sum(o.qty for o in t.entry_orders)
        q_out = sum(o.qty for o in t.exit_orders)
        n_in = sum(o.qty * o.price for o in t.entry_orders)
        n_out = sum(o.qty * o.price for o in t.exit_orders)
        et = t.entry_ts.tz_convert("America/New_York")
        rows.append(
            {
                "symbol": t.symbol,
                "contract": t.contract,
                "side": "Long" if t.direction > 0 else "Short",
                "qty": q_in,
                "entry_time": t.entry_ts,
                "exit_time": t.exit_ts,
                "entry_price": n_in / q_in,
                "exit_price": n_out / q_out,
                "gross_pnl": t.direction * mult * (n_out - n_in),
                "commissions": rate * (q_in + q_out),
                "entry_sigma": t.sigma,
                "hour_et": et.hour,
                "weekday": et.dayofweek,
                "duration_min": (t.exit_ts - t.entry_ts).total_seconds() / 60,
            }
        )
    truth = pd.DataFrame(rows).sort_values("entry_time").reset_index(drop=True)
    truth["net_pnl"] = truth["gross_pnl"] - truth["commissions"]
    return truth
