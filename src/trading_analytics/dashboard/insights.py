"""Plain-English findings, each with its sample size and an honest statement of evidence.

Rules the module enforces (so the dashboard cannot over-claim):
- every finding carries n, the number of trades it rests on;
- conditions are only ranked on knowable-before-entry dimensions (never trade duration, which is
  an outcome in disguise) and only for buckets with at least MIN_BUCKET_N trades;
- "best / worst condition" is tested with a permutation test and corrected for the number of
  dimensions examined (Bonferroni), so scanning ten slicings does not manufacture a winner;
- a result that a shuffle of the labels would produce this often is called "not significant".
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from trading_analytics.stats import permutation_pvalue, signflip_pvalue

MIN_BUCKET_N = 30
MIN_TRADES_FOR_CONDITIONS = 60
MIN_TRADES_FOR_EDGE = 10
ALPHA = 0.05
MAX_INSIGHTS = 5


@dataclass(frozen=True)
class Insight:
    kind: str  # edge | best | worst | conditions | costs | streaks
    headline: str
    detail: str
    n: int  # trades the statement rests on
    evidence: str  # significant | not significant | descriptive | insufficient data


def usd(x: float) -> str:
    return f"{'-' if x < 0 else '+'}${abs(x):,.0f}"


def labels_for(trades: pd.DataFrame) -> dict[str, pd.Series]:
    """Per-trade bucket labels for the ex-ante dimensions (same buckets as the SQL mart)."""
    d = trades["dist_from_open_signed_pts"]
    return {
        "hour": trades["hour_et"].astype(str),
        "weekday": trades["weekday"],
        "time_bucket": trades["time_bucket"],
        "session": trades["session"],
        "vol_regime": trades["vol_regime"].fillna("n/a"),
        "vix_regime": trades["vix_regime"].fillna("n/a"),
        "side": trades["side"],
        "symbol": trades["symbol"],
        "open_alignment": pd.Series(
            np.where(
                d.isna(),
                "n/a",
                np.where(
                    d > 0,
                    "with the day move",
                    np.where(d < 0, "against the day move", "at the open"),
                ),
            ),
            index=trades.index,
        ),
    }


def _edge(trades: pd.DataFrame, k: pd.Series) -> Insight:
    n = int(k["n_trades"])
    if n < MIN_TRADES_FOR_EDGE:
        return Insight(
            "edge",
            f"Only {n} trades: too few to judge your edge",
            f"At least {MIN_TRADES_FOR_EDGE} trades are needed to say anything, and "
            "hundreds to say something reliable.",
            n,
            "insufficient data",
        )
    net = trades["net_pnl"].to_numpy()
    p = signflip_pvalue(net)
    se = net.std(ddof=1) / np.sqrt(n)
    pf = k["profit_factor"]
    pf_txt = f" Profit factor {pf:.2f}." if pd.notna(pf) else ""
    if p < ALPHA:
        head = f"Your average trade is {usd(k['expectancy_net'])} net, unlikely to be luck"
        ev = "significant"
        detail = f"p = {p:.3f}: a zero-edge trader would rarely do this well or badly.{pf_txt}"
    else:
        head = (
            f"Your average trade is {usd(k['expectancy_net'])} net, not distinguishable from zero"
        )
        ev = "not significant"
        detail = (
            f"p = {p:.2f}; the standard error of that average is about ±${se:,.0f} per "
            f"trade, so the data cannot tell skill from luck yet.{pf_txt}"
        )
    return Insight("edge", head, detail, n, ev)


def _conditions(trades: pd.DataFrame, dims: pd.DataFrame, seed: int) -> list[Insight]:
    n = len(trades)
    cand = dims[dims["is_actionable"] & (dims["n_trades"] >= MIN_BUCKET_N)]
    if n < MIN_TRADES_FOR_CONDITIONS or cand.empty:
        return [
            Insight(
                "conditions",
                "Not enough trades to compare conditions",
                f"Comparing hours, weekdays or volatility needs at least {MIN_BUCKET_N} trades in "
                "a "
                f"bucket (and about {MIN_TRADES_FOR_CONDITIONS} in total); you have {n}.",
                n,
                "insufficient data",
            )
        ]
    labels, tested = labels_for(trades), sorted(cand["dimension"].unique())
    k = len(tested)
    adj = {
        dim: min(1.0, k * permutation_pvalue(trades["net_pnl"], labels[dim], 2000, seed))
        for dim in tested
    }
    overall = trades["net_pnl"].mean()
    out = []
    for kind, row in (
        ("best", cand.loc[cand["expectancy_net"].idxmax()]),
        ("worst", cand.loc[cand["expectancy_net"].idxmin()]),
    ):
        p = adj[row["dimension"]]
        name = f"{row['dimension']} = {row['bucket']}"
        head = (
            f"{'Best' if kind == 'best' else 'Weakest'} condition: {name}, "
            f"{usd(row['expectancy_net'])} per trade"
        )
        base = (
            f"{int(row['n_trades'])} trades, win rate {row['win_rate']:.0%}, versus "
            f"{usd(overall)} per trade overall."
        )
        if p < ALPHA:
            detail = (
                f"{base} Differences across {row['dimension']} are unlikely to be chance "
                f"(adjusted p = {p:.3f}, corrected for {k} dimensions examined)."
            )
            ev = "significant"
        else:
            detail = (
                f"{base} But differences across {row['dimension']} are within what chance "
                f"produces (adjusted p = {p:.2f}, corrected for {k} dimensions examined). "
                "Treat it as a lead to re-test on new trades, not a rule."
            )
            ev = "not significant"
        out.append(Insight(kind, head, detail, int(row["n_trades"]), ev))
    return out


def _costs(trades: pd.DataFrame, k: pd.Series) -> Insight | None:
    n = int(k["n_trades"])
    if n == 0 or not k["gross_profit"]:
        return None
    per_trade = k["costs"] / n
    share = k["costs_pct_of_gross_profit"]
    head = f"Commissions and fees cost {share:.1%} of your gross winnings"
    detail = f"That is about ${per_trade:,.2f} per trade ({usd(-k['costs'])} in total)."
    if k["gross_pnl"] > 0 > k["net_pnl"]:
        detail += " They turn a gross profit into a net loss."
    elif k["gross_pnl"] > 0:
        detail += f" They take {k['costs'] / k['gross_pnl']:.0%} of your gross P&L."
    return Insight("costs", head, detail, n, "descriptive")


def _longest_runs(outcomes: np.ndarray, code: int) -> np.ndarray:
    cur = np.zeros(outcomes.shape[0], dtype=int)
    best = np.zeros_like(cur)
    for col in range(outcomes.shape[1]):
        cur = np.where(outcomes[:, col] == code, cur + 1, 0)
        best = np.maximum(best, cur)
    return best


def _streaks(k: pd.Series, seed: int, sims: int = 2000) -> Insight | None:
    n = int(k["n_trades"])
    if n < 30:
        return None
    shares = np.array([k["n_wins"], k["n_losses"], k["n_scratch"]], dtype=float) / n
    rng = np.random.default_rng(seed)
    draw = rng.choice(3, size=(sims, n), p=shares)  # 0 win, 1 loss, 2 scratch (breaks runs)
    lose_runs = _longest_runs(draw, 1)
    observed = int(k["max_loss_streak"])
    p95 = int(np.percentile(lose_runs, 95))
    frac = float((lose_runs >= observed).mean())
    head = f"Your longest losing streak is {observed} trades"
    if observed > p95:
        detail = (
            f"Random sequences with your win rate reach that in only {frac:.1%} of runs "
            f"(95% stay at {p95} or fewer), so losses may be clustering; look at what "
            "those trades had in common."
        )
        ev = "significant"
    else:
        detail = (
            f"That is normal for {n} trades at your win rate: {frac:.0%} of random "
            f"sequences contain a losing run at least as long (typical maximum {p95} or "
            "fewer). Streaks alone are not a sign something changed."
        )
        ev = "not significant"
    return Insight("streaks", head, detail, n, ev)


def generate_insights(
    trades: pd.DataFrame, kpis: pd.Series, dims: pd.DataFrame, seed: int = 0
) -> list[Insight]:
    """3-5 findings from filtered trades, their KPI row and the dimension mart."""
    if trades.empty:
        return []
    found = [_edge(trades, kpis), *_conditions(trades, dims, seed)]
    for extra in (_costs(trades, kpis), _streaks(kpis, seed)):
        if extra is not None:
            found.append(extra)
    return found[:MAX_INSIGHTS]
