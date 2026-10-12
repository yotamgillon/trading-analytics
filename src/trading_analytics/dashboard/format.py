"""Display helpers shared by the app and its tests."""

import pandas as pd

# Mart dimension ids -> what a person calls them.
DIMENSION_LABELS = {
    "hour": "Entry hour (ET)",
    "weekday": "Weekday",
    "time_bucket": "Time of day",
    "session": "Session",
    "vol_regime": "Volatility regime",
    "vix_regime": "VIX regime",
    "duration": "Trade duration",
    "side": "Direction",
    "symbol": "Symbol",
    "open_alignment": "Vs the day's move",
}

TABLE_COLUMNS = {
    "dimension": "Condition",
    "bucket": "Bucket",
    "n_trades": "Trades",
    "win_rate": "Win rate",
    "expectancy_net": "Expectancy",
    "profit_factor": "Profit factor",
    "net_pnl": "Net P&L",
}


def fmt_money(x, decimals: int = 0) -> str:
    """-$68.87, never $-68.87."""
    if pd.isna(x):
        return "n/a"
    return f"{'-' if x < 0 else ''}${abs(x):,.{decimals}f}"


def fmt_pct(x, decimals: int = 0) -> str:
    return "n/a" if pd.isna(x) else f"{x:.{decimals}%}"


def fmt_num(x, decimals: int = 2) -> str:
    return "n/a" if pd.isna(x) else f"{x:.{decimals}f}"


def condition_table(df: pd.DataFrame):
    """A styled, human-readable conditions table (used for best and worst)."""
    shown = df[list(TABLE_COLUMNS)].assign(dimension=lambda d: d["dimension"].map(DIMENSION_LABELS))
    shown = shown.rename(columns=TABLE_COLUMNS)
    return shown.style.format(
        {
            "Win rate": fmt_pct,
            "Expectancy": lambda v: fmt_money(v, 2),
            "Profit factor": fmt_num,
            "Net P&L": fmt_money,
        }
    )
