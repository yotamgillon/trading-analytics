"""Synthetic NQ 1-minute bars and a daily VIX-like series for the public demo.

The price process is a driftless random walk (zero expected return) with:
- daily volatility that is persistent (AR(1) in log-vol), so there are real vol regimes;
- an intraday U-shaped volatility profile (busy open and close), as in real index futures;
- fat tails (Student-t shocks) and tick-rounded OHLC.
Nothing here depends on any trader, so it cannot carry an edge for the demo trades.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from trading_analytics.market.sessions import HOLIDAYS as SESSION_HOLIDAYS

ET = ZoneInfo("America/New_York")
TICK = 0.25
BARS_PER_DAY = 480  # 08:30-16:29 ET start times
RTH_OFFSET = 60  # bar index of 09:30 ET
RTH_BARS = 390
SUBSTEPS = 6  # micro-steps per bar so high/low are realistic
START_PRICE = 30_000.0

# Same holiday table as the real-market calendar (no bars, no trades on those days).
HOLIDAYS = SESSION_HOLIDAYS


def trading_days(start: date, n_days: int) -> list[date]:
    days, d = [], start
    while len(days) < n_days:
        if d.weekday() < 5 and d not in HOLIDAYS:
            days.append(d)
        d += timedelta(days=1)
    return days


def round_tick(x):
    return np.round(np.asarray(x) / TICK) * TICK


def _shape() -> np.ndarray:
    """Relative per-bar variance: U-shape inside RTH, quiet outside."""
    m = np.arange(BARS_PER_DAY)
    r = m - RTH_OFFSET
    shape = np.where(
        (r >= 0) & (r < RTH_BARS),
        1.0 + 2.0 * np.exp(-r / 20.0) + 1.0 * np.exp(-(RTH_BARS - 1 - r) / 30.0),
        np.where(r < 0, 0.4, 0.5),
    )
    return shape


@dataclass
class DayBars:
    day: date
    ts: pd.DatetimeIndex  # bar start times, UTC
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray  # noqa: E741
    c: np.ndarray
    daily_sigma: float


def generate_market(
    days: list[date], seed: int
) -> tuple[list[DayBars], pd.DataFrame, pd.DataFrame]:
    """Return per-day arrays (for the trade simulator), a bars frame and a daily VIX frame."""
    rng = np.random.default_rng([seed, 1])
    mu = np.log(0.012)
    log_sigma, sigmas = mu, []
    for _ in days:
        log_sigma = mu + 0.93 * (log_sigma - mu) + rng.normal(0, 0.12)
        sigmas.append(float(np.exp(log_sigma)))

    shape = _shape()
    rth_norm = shape[RTH_OFFSET : RTH_OFFSET + RTH_BARS].sum()
    scale_t = np.sqrt(5 / 3)  # unit-variance Student-t with 5 dof

    price = START_PRICE
    out: list[DayBars] = []
    for day, sigma in zip(days, sigmas, strict=True):
        price *= float(np.exp(rng.normal(0, 0.4 * sigma)))  # overnight gap
        var_bar = sigma**2 * shape / rth_norm
        steps = rng.standard_t(5, size=(BARS_PER_DAY, SUBSTEPS)) / scale_t
        steps *= np.sqrt(var_bar / SUBSTEPS)[:, None] * price
        path = price + np.cumsum(steps.ravel())
        close = path[SUBSTEPS - 1 :: SUBSTEPS]
        open_ = np.concatenate(([price], close[:-1]))
        grid = path.reshape(BARS_PER_DAY, SUBSTEPS)
        high = np.maximum(grid.max(axis=1), open_)
        low = np.minimum(grid.min(axis=1), open_)
        price = float(close[-1])
        local_open = pd.Timestamp(day.isoformat() + " 08:30", tz=ET)
        ts = pd.date_range(local_open, periods=BARS_PER_DAY, freq="min").tz_convert("UTC")
        out.append(
            DayBars(
                day,
                ts,
                round_tick(open_),
                round_tick(high),
                round_tick(low),
                round_tick(close),
                sigma,
            )
        )

    rows = []
    vol_scale = 600 * shape / shape.mean()
    for d in out:
        volume = rng.lognormal(0, 0.35, BARS_PER_DAY) * vol_scale
        rows.append(
            pd.DataFrame(
                {
                    "symbol": "NQ=F",
                    "ts": d.ts,
                    "open": d.o,
                    "high": d.h,
                    "low": d.l,
                    "close": d.c,
                    "volume": volume.astype("int64"),
                }
            )
        )
    bars = pd.concat(rows, ignore_index=True)

    vix = pd.DataFrame(
        {
            "date": days,
            "close": np.clip(
                [100 * s * np.sqrt(252) * 0.9 + rng.normal(0, 0.8) for s in sigmas], 9.0, None
            ).round(2),
        }
    )
    return out, bars, vix
