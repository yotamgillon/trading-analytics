"""Public demo data: synthetic raw Tradovate fills + synthetic 1-min bars + synthetic VIX."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from trading_analytics.demo.market import generate_market, trading_days
from trading_analytics.demo.trades import build_raw_export, generate_trades

DEFAULT_SEED = 2026


@dataclass
class DemoData:
    raw_fills: pd.DataFrame  # exactly the columns/format of a Tradovate Fills.csv export
    bars_1m: pd.DataFrame
    vix_daily: pd.DataFrame
    truth_trades: pd.DataFrame  # generator's own trade list, for tests only (never written)


def generate_demo(
    seed: int = DEFAULT_SEED, n_trades: int = 500, n_days: int = 135, start: date = date(2026, 1, 5)
) -> DemoData:
    days = trading_days(start, n_days)
    day_bars, bars, vix = generate_market(days, seed)
    rng = np.random.default_rng([seed, 2])
    trades = generate_trades(day_bars, n_trades, rng)
    raw, truth = build_raw_export(trades, rng)
    return DemoData(raw, bars, vix, truth)


def write_demo(out_dir: str | Path = "data/demo", **kwargs) -> DemoData:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    demo = generate_demo(**kwargs)
    demo.raw_fills.to_csv(out / "Fills.csv", index=False)
    demo.bars_1m.to_parquet(out / "bars_1m.parquet", index=False)
    demo.vix_daily.to_parquet(out / "vix_daily.parquet", index=False)
    return demo
