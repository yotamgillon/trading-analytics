"""Yahoo Finance fetching with retries, chunking and validation.

Yahoo only serves ~7 days of 1-minute and ~60 days of 5-minute history, so bars must be
accumulated by a scheduled job; anything older than the window can never be recovered.
The network client is injected (`Fetcher`), so every test runs offline.
"""

import logging
import time as _time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# (max days per request, how far back we try to fetch, how far back we TRUST a gap is fixable).
# The last number is deliberately conservative (the project's known ~7-day / ~60-day constraint).
LIMITS = {"1m": (7, 29, 7), "5m": (30, 59, 55), "1d": (3650, 36500, 36500)}
INTERVAL_MINUTES = {"1m": 1, "5m": 5, "1d": 1440}

# Callable(symbol, interval, start, end) -> raw Yahoo-style frame (tz-aware index, OHLCV columns)
Fetcher = Callable[[str, str, datetime, datetime], pd.DataFrame]


class FetchError(RuntimeError):
    pass


def yahoo_fetcher(symbol: str, interval: str, start: datetime, end: datetime) -> pd.DataFrame:
    import yfinance as yf  # imported lazily: tests and the demo never touch the network

    return yf.Ticker(symbol).history(
        interval=interval, start=start, end=end, auto_adjust=False, prepost=True, actions=False
    )


def normalize(raw: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Yahoo frame -> clean OHLCV indexed by UTC; returns (clean, number of rows dropped)."""
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"]), 0
    df = raw.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].copy()
    df.index = pd.DatetimeIndex(df.index).tz_convert("UTC")
    df.index.name = "ts"
    n_in = len(df)
    df = df[~df.index.duplicated(keep="last")]
    ohlc = df[["open", "high", "low", "close"]]
    ok = np.isfinite(ohlc).all(axis=1) & (ohlc > 0).all(axis=1) & (df["high"] >= df["low"])
    df = df[ok].copy()
    df["volume"] = df["volume"].fillna(0).astype("int64")
    return df.sort_index(), n_in - len(df)


def fetch_with_retry(
    fetcher: Fetcher,
    symbol: str,
    interval: str,
    start: datetime,
    end: datetime,
    *,
    expects_data: bool = True,
    attempts: int = 4,
    base_delay: float = 2.0,
    sleep: Callable[[float], None] = _time.sleep,
) -> pd.DataFrame:
    """Exponential backoff on exceptions, and on empty results when data is expected."""
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            raw = fetcher(symbol, interval, start, end)
            if raw is not None and not raw.empty:
                return raw
            last = FetchError("empty result")
            if not expects_data:
                return raw
        except Exception as exc:  # network, rate limit, Yahoo errors: all retryable
            last = exc
        if attempt < attempts:
            delay = base_delay * 2 ** (attempt - 1)
            log.warning(
                "%s %s attempt %d failed (%s); retrying in %.0fs",
                symbol,
                interval,
                attempt,
                last,
                delay,
            )
            sleep(delay)
    raise FetchError(
        f"{symbol} {interval} {start:%F}..{end:%F} failed after {attempts} attempts: {last}"
    )


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime


def chunk_windows(interval: str, start: datetime, end: datetime, now: datetime) -> list[Window]:
    """Split [start, end) into request-sized windows, clamped to what Yahoo still serves."""
    max_days, back_days, _ = LIMITS[interval]
    earliest = now - timedelta(days=back_days)
    if start < earliest:
        log.warning(
            "%s: start %s is older than Yahoo serves; clamped to %s", interval, start, earliest
        )
        start = earliest
    windows, cur = [], start
    while cur < end:
        nxt = min(cur + timedelta(days=max_days), end)
        windows.append(Window(cur, nxt))
        cur = nxt
    return windows
