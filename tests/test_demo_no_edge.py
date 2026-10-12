"""The demo must not contain a pattern for the dashboard to 'discover'.

Gross P&L (the trader's skill; net is gross minus costs) and win rate are compared across every
ex-ante slicing the dashboard offers (hour, weekday, volatility regime, side, symbol, size) with
permutation tests. Trade duration is deliberately NOT tested: it is only known after the trade
and is mechanically coupled to the outcome (a closer stop is hit sooner than a farther target),
so any duration "pattern" is an artifact of stop/target exits, not an edge. The Insights section
must not present it as an actionable condition.
"""

import numpy as np
import pandas as pd
import pytest

from trading_analytics.demo import DEFAULT_SEED, generate_demo
from trading_analytics.ingest.instruments import INSTRUMENTS
from trading_analytics.stats import permutation_pvalue

MULT = {k: v.multiplier for k, v in INSTRUMENTS.items()}


def features(t: pd.DataFrame) -> dict[str, pd.Series]:
    return {
        "hour": t["hour_et"],
        "weekday": t["weekday"],
        "vol_regime": pd.qcut(t["entry_sigma"], 3, labels=False, duplicates="drop"),
        "side": t["side"],
        "symbol": t["symbol"],
        "size": pd.cut(t["qty"], [0, 1, 3, 100]),
    }


def pvalues(t: pd.DataFrame, n_perm: int) -> dict[str, float]:
    # points per contract: removes the NQ/MNQ multiplier and the size mix from the variance
    pnl = t["gross_pnl"] / (t["qty"] * t["symbol"].map(MULT))
    win = (t["gross_pnl"] > 0).astype(float)
    out = {}
    for name, labels in features(t).items():
        out[f"{name}/pnl"] = permutation_pvalue(pnl, labels, n_perm, seed=1)
        out[f"{name}/win"] = permutation_pvalue(win, labels, n_perm, seed=2)
    return out


def test_shipped_demo_has_no_significant_pattern():
    t = generate_demo(DEFAULT_SEED).truth_trades
    p = pvalues(t, n_perm=1000)
    # 12 tests: a 1% threshold per test keeps the family-wise false alarm rate near 11%.
    assert min(p.values()) > 0.01, p


def test_gross_expectancy_is_not_distinguishable_from_zero():
    t = generate_demo(DEFAULT_SEED).truth_trades
    per_contract = (t["gross_pnl"] / (t["qty"] * t["symbol"].map(MULT))).to_numpy()
    se = per_contract.std(ddof=1) / np.sqrt(len(per_contract))
    assert abs(per_contract.mean()) < 3 * se


def test_net_loss_comes_from_costs_not_from_a_hidden_negative_edge():
    t = generate_demo(DEFAULT_SEED).truth_trades
    assert t["commissions"].sum() > 0
    assert t["net_pnl"].sum() == pytest.approx(t["gross_pnl"].sum() - t["commissions"].sum())


def test_false_alarm_rate_is_calibrated_across_seeds():
    """If the generator hid an edge, p-values across seeds would pile up near 0."""
    n_seeds, alpha = 12, 0.01
    rejections = total = 0
    for seed in range(100, 100 + n_seeds):
        t = generate_demo(seed).truth_trades
        for p in pvalues(t, n_perm=300).values():
            rejections += p < alpha
            total += 1
    # Expected ~1% (about 2 of 144); 8 would be a ~4x excess.
    assert rejections <= 8, f"{rejections}/{total} tests rejected at {alpha}"


def test_the_tests_have_power_a_planted_edge_is_detected():
    """Guard against vacuous tests: plant +40 points/contract at 10:00 ET, expect a tiny p-value."""
    t = generate_demo(DEFAULT_SEED).truth_trades.copy()
    mask = t["hour_et"] == 10
    t.loc[mask, "gross_pnl"] += 40 * t.loc[mask, "qty"] * t.loc[mask, "symbol"].map(MULT)
    assert pvalues(t, n_perm=500)["hour/pnl"] < 0.01
