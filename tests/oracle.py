"""Independent pandas/numpy implementations of the metrics, shared by the tests."""

import itertools

import numpy as np
import pandas as pd
import pytest


def pandas_metrics(t: pd.DataFrame) -> dict:
    win, loss = t["gross_pnl"] > 0, t["gross_pnl"] < 0
    gp, gl = t.loc[win, "gross_pnl"].sum(), t.loc[loss, "gross_pnl"].sum()
    nw, nl = t["net_pnl"] > 0, t["net_pnl"] < 0
    costs = t["commissions"].sum() + t["fees"].sum()
    return {
        "n_trades": len(t),
        "n_wins": int(win.sum()),
        "n_losses": int(loss.sum()),
        "n_scratch": int((~win & ~loss).sum()),
        "win_rate": win.mean(),
        "avg_win": t.loc[win, "gross_pnl"].mean() if win.any() else np.nan,
        "avg_loss": t.loc[loss, "gross_pnl"].mean() if loss.any() else np.nan,
        "expectancy_gross": t["gross_pnl"].mean(),
        "expectancy_net": t["net_pnl"].mean(),
        "profit_factor": gp / abs(gl) if gl else np.nan,
        "profit_factor_net": t.loc[nw, "net_pnl"].sum() / abs(t.loc[nl, "net_pnl"].sum())
        if nl.any()
        else np.nan,
        "gross_pnl": t["gross_pnl"].sum(),
        "net_pnl": t["net_pnl"].sum(),
        "costs": costs,
        "costs_pct_of_gross_profit": costs / gp if gp else np.nan,
        "avg_duration_min": t["duration_min"].mean(),
    }


def path_stats(t: pd.DataFrame):
    t = t.sort_values(["exit_time", "trade_id"])
    equity = t["net_pnl"].cumsum().to_numpy()
    peak = np.maximum.accumulate(np.concatenate([[0.0], equity]))[1:]
    outcomes = np.where(t["gross_pnl"] > 0, "win", np.where(t["gross_pnl"] < 0, "loss", "scratch"))
    runs = {"win": 0, "loss": 0}
    for key, grp in itertools.groupby(outcomes):
        if key != "scratch":
            runs[key] = max(runs[key], len(list(grp)))
    return (peak - equity).max(), runs["win"], runs["loss"]


def close(a, b):
    return (pd.isna(a) and pd.isna(b)) or a == pytest.approx(b, rel=1e-9, abs=1e-9)
