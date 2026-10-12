"""Three clocks, one source of truth.

The platform's `_timestamp` is UTC and is the only stored time. Everything else is derived:
- exchange time (CME runs on America/Chicago),
- US Eastern (how most traders and the equity open at 09:30 are quoted),
- Israel time (what the platform's display column and the user's clock show).
US and Israeli daylight-saving dates differ, so the ET-Israel gap is 7h most of the year but
6h for a few weeks in March and 1h-shifted in late October. Hard-coding an offset would be wrong.
"""

import pandas as pd

EXCHANGE_TZ = "America/Chicago"
ET_TZ = "America/New_York"
ISRAEL_TZ = "Asia/Jerusalem"


def to_exchange(ts: pd.Series) -> pd.Series:
    return ts.dt.tz_convert(EXCHANGE_TZ)


def to_et(ts: pd.Series) -> pd.Series:
    return ts.dt.tz_convert(ET_TZ)


def to_israel(ts: pd.Series) -> pd.Series:
    return ts.dt.tz_convert(ISRAEL_TZ)


def add_local_times(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """Add <col>_exchange, <col>_et and <col>_israel (tz-aware) next to a UTC column."""
    out = df.copy()
    out[f"{col}_exchange"] = to_exchange(out[col])
    out[f"{col}_et"] = to_et(out[col])
    out[f"{col}_israel"] = to_israel(out[col])
    return out


def session_trade_date(ts: pd.Series) -> pd.Series:
    """CME trade date: the Globex session opens 18:00 ET (17:00 CT) and belongs to the next day."""
    return (to_et(ts) + pd.Timedelta(hours=6)).dt.date
