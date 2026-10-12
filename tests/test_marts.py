"""Marts vs independent computations: a hand-checked fixture and a pandas oracle on the demo."""

import itertools
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import duckdb
import numpy as np
import pandas as pd
import pytest
from scripts.transform import run_dbt

from trading_analytics.ingest.instruments import INSTRUMENTS
from trading_analytics.warehouse import build_warehouse

RAW_COLS = (
    "_id,_orderId,_contractId,_timestamp,_tradeDate,_action,_qty,_price,_active,_accountId,"
    "Fill ID,Order ID,Timestamp,Date,Account,B/S,Quantity,Price,_priceFormat,_priceFormatType,"
    "_tickSize,Contract,Product,Product Description,commission"
).split(",")
RATE = {"NQ": 1.75, "MNQ": 0.5}
IL, ET = ZoneInfo("Asia/Jerusalem"), ZoneInfo("America/New_York")


def raw_fills(rows):
    """rows: (utc 'YYYY-MM-DD HH:MM', 'Buy'|'Sell', qty, price, product). Fully synthetic."""
    out = []
    for n, (ts, side, qty, price, product) in enumerate(rows, start=1):
        t = datetime.strptime(ts, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)  # noqa: UP017
        loc = t.astimezone(IL)
        out.append(
            {
                "_id": 900_000_001_000 + n,
                "_orderId": 900_000_001_000 + n,
                "_contractId": 1,
                "_timestamp": t.strftime("%Y-%m-%d %H:%M:%S.000Z"),
                "_tradeDate": t.astimezone(ET).date().isoformat(),
                "_action": 0 if side == "Buy" else 1,
                "_qty": qty,
                "_price": price,
                "_active": "true",
                "_accountId": 1,
                "Fill ID": 900_000_001_000 + n,
                "Order ID": 900_000_001_000 + n,
                "Timestamp": loc.strftime("%m/%d/%Y %H:%M:%S"),
                "Date": f"{loc.month}/{loc.day}/{loc.year % 100:02d}",
                "Account": "FIXTURE",
                "B/S": " " + side,
                "Quantity": qty,
                "Price": f"{price:.2f}",
                "_priceFormat": -2,
                "_priceFormatType": 0,
                "_tickSize": 0.25,
                "Contract": f"{product}H0",
                "Product": product,
                "Product Description": product,
                "commission": qty * RATE[product],
            }
        )
    return pd.DataFrame(out, columns=RAW_COLS).astype(str)


# Nine trades, one at a time; gross $ = points x multiplier x qty. NQ x1 costs $3.50 round trip.
FIXTURE = [
    ("2030-01-07 14:30", "Buy", 1, 20000.0, "NQ"),
    ("2030-01-07 14:35", "Sell", 1, 20005.0, "NQ"),  # +100 W
    ("2030-01-07 14:40", "Buy", 1, 20010.0, "NQ"),
    ("2030-01-07 14:45", "Sell", 1, 20007.5, "NQ"),  # -50 L
    ("2030-01-07 14:50", "Sell", 1, 20000.0, "NQ"),
    ("2030-01-07 14:55", "Buy", 1, 20001.5, "NQ"),  # -30 L
    ("2030-01-08 15:00", "Buy", 1, 20000.0, "NQ"),
    ("2030-01-08 15:05", "Sell", 1, 20002.0, "NQ"),  # +40 W
    ("2030-01-08 15:10", "Buy", 1, 20000.0, "NQ"),
    ("2030-01-08 15:15", "Sell", 1, 20000.0, "NQ"),  # 0 scratch
    ("2030-01-09 15:00", "Buy", 1, 20000.0, "NQ"),
    ("2030-01-09 15:05", "Sell", 1, 20000.5, "NQ"),  # +10 W
    ("2030-01-09 15:10", "Sell", 1, 20010.0, "NQ"),
    ("2030-01-09 15:15", "Buy", 1, 20000.0, "NQ"),  # +200 W
    ("2030-01-09 15:20", "Buy", 1, 20000.0, "NQ"),
    ("2030-01-09 15:25", "Sell", 1, 19990.0, "NQ"),  # -200 L
    ("2030-01-09 16:00", "Buy", 5, 20000.0, "MNQ"),
    ("2030-01-09 16:05", "Sell", 5, 20004.0, "MNQ"),  # +40 W
]


def build(tmp_path, rows=None, source=None, dbt_vars=None):
    csv = tmp_path / "Fills.csv"
    if rows is not None:
        raw_fills(rows).to_csv(csv, index=False)
    db = tmp_path / "w.duckdb"
    build_warehouse("demo", db_path=db, fills_path=csv if rows is not None else source)
    assert run_dbt(db, quiet=True, dbt_vars=dbt_vars) == 0, "dbt build (incl. mart tests) failed"
    return duckdb.connect(str(db), read_only=True)


def row(con, sql):
    return con.execute(sql).fetchdf().iloc[0]


@pytest.fixture(scope="module")
def fx(tmp_path_factory):
    return build(tmp_path_factory.mktemp("fx"), FIXTURE)


# ---- hand-computed expectations (see FIXTURE comments) ----------------------------------
def test_kpis_match_hand_computation(fx):
    k = row(fx, "select * from marts.mart_kpis where symbol_scope = 'ALL'")
    assert (k.n_trades, k.n_wins, k.n_losses, k.n_scratch) == (9, 5, 3, 1)
    assert k.win_rate == pytest.approx(5 / 9)
    assert k.gross_profit == 390 and k.gross_loss == -280 and k.gross_pnl == 110
    assert k.commissions == 33 and k.net_pnl == 77
    assert k.avg_win == pytest.approx(78) and k.avg_loss == pytest.approx(-280 / 3)
    assert k.payoff_ratio == pytest.approx(78 / (280 / 3))
    assert k.expectancy_gross == pytest.approx(110 / 9) and k.expectancy_net == pytest.approx(
        77 / 9
    )
    assert k.profit_factor == pytest.approx(390 / 280)
    assert k.profit_factor_net == pytest.approx(371 / 294)  # net wins 371, net losses -294
    assert k.costs == 33 and k.costs_pct_of_gross_profit == pytest.approx(33 / 390)
    assert k.costs_pct_of_gross_pnl == pytest.approx(33 / 110)
    assert (k.max_win_streak, k.max_loss_streak) == (2, 2)  # the scratch splits W,S,W
    assert k.max_drawdown_usd == pytest.approx(203.5)
    assert (k.best_trade_net, k.worst_trade_net) == pytest.approx((196.5, -203.5))
    assert k.trading_days == 3 and pd.Timestamp(k.first_trade_date).date() == date(2030, 1, 7)


def test_symbol_scopes(fx):
    nq = row(fx, "select * from marts.mart_kpis where symbol_scope = 'NQ'")
    mnq = row(fx, "select * from marts.mart_kpis where symbol_scope = 'MNQ'")
    assert (nq.n_trades, nq.n_wins, nq.net_pnl, nq.gross_profit) == (8, 4, 42, 350)
    assert (mnq.n_trades, mnq.n_wins, mnq.net_pnl, mnq.commissions) == (1, 1, 35, 5)
    assert mnq.profit_factor is None or pd.isna(mnq.profit_factor)  # no losing trade


def test_equity_curve_and_drawdown_start_from_zero(fx):
    c = fx.execute(
        "select * from marts.mart_equity_curve where symbol_scope = 'ALL' order by trade_seq"
    ).fetchdf()
    assert c["equity"].tolist() == pytest.approx([96.5, 43, 9.5, 46, 42.5, 49, 245.5, 42, 77])
    assert c["peak_equity"].tolist() == pytest.approx(
        [96.5, 96.5, 96.5, 96.5, 96.5, 96.5, 245.5, 245.5, 245.5]
    )
    assert c["drawdown_usd"].max() == pytest.approx(203.5)
    assert c["drawdown_pct"].isna().all()  # no starting balance -> % is undefined, not guessed


def test_a_losing_start_is_a_drawdown_from_the_starting_point(tmp_path):
    rows = [
        ("2030-01-07 14:30", "Buy", 1, 20000.0, "NQ"),
        ("2030-01-07 14:35", "Sell", 1, 19995.0, "NQ"),
    ]
    con = build(tmp_path, rows)  # one loser: -100 gross, -103.5 net, start_balance 0
    c = row(con, "select * from marts.mart_equity_curve where symbol_scope = 'ALL'")
    assert c.equity == pytest.approx(-103.5) and c.peak_equity == 0
    assert c.drawdown_usd == pytest.approx(103.5)


def test_drawdown_percent_with_a_starting_balance(tmp_path):
    con = build(tmp_path, FIXTURE, dbt_vars="{start_balance: 50000}")
    c = con.execute(
        "select * from marts.mart_equity_curve where symbol_scope = 'ALL' order by trade_seq"
    ).fetchdf()
    assert c["equity"].iloc[0] == pytest.approx(50096.5)
    assert c["drawdown_usd"].max() == pytest.approx(203.5)  # dollars do not depend on the balance
    assert c["drawdown_pct"].max() == pytest.approx(203.5 / 50245.5)
    k = row(con, "select * from marts.mart_kpis where symbol_scope = 'ALL'")
    assert k.max_drawdown_pct == pytest.approx(203.5 / 50245.5)


def test_streaks_mart(fx):
    s = fx.execute(
        "select outcome, streak_len from marts.mart_streaks where symbol_scope = 'ALL' "
        "order by streak_id"
    ).fetchall()
    assert s == [("win", 1), ("loss", 2), ("win", 1), ("win", 2), ("loss", 1), ("win", 1)]


def test_daily_mart_is_additive_and_per_day(fx):
    d = fx.execute(
        "select trade_date, symbol, n_trades, net_pnl from marts.mart_daily_performance "
        "order by trade_date, symbol"
    ).fetchall()
    assert d == [
        (date(2030, 1, 7), "NQ", 3, pytest.approx(9.5)),
        (date(2030, 1, 8), "NQ", 2, pytest.approx(33)),
        (date(2030, 1, 9), "MNQ", 1, pytest.approx(35)),
        (date(2030, 1, 9), "NQ", 3, pytest.approx(-0.5)),
    ]


def test_win_loss_basis_can_be_net(tmp_path):
    con = build(tmp_path, FIXTURE, dbt_vars="{win_loss_basis: net}")
    k = row(con, "select * from marts.mart_kpis where symbol_scope = 'ALL'")
    assert (k.n_wins, k.n_losses, k.n_scratch) == (5, 4, 0)  # the scratch now loses its costs
    assert k.avg_win == pytest.approx(78)  # avg win/loss stay GROSS, classified by net


def test_dimensions_partition_the_fixture(fx):
    wd = fx.execute(
        "select bucket, n_trades, net_pnl from marts.mart_perf_by_dimension "
        "where dimension = 'weekday' order by bucket_order"
    ).fetchall()
    assert wd == [
        ("Monday", 3, pytest.approx(9.5)),
        ("Tuesday", 2, pytest.approx(33)),
        ("Wednesday", 4, pytest.approx(34.5)),
    ]
    flag = fx.execute(
        "select dimension, bool_and(is_actionable) from marts.mart_perf_by_dimension "
        "group by 1 order by 1"
    ).fetchall()
    assert dict(flag)["duration"] is False and dict(flag)["hour"] is True


# ---- independent pandas oracle on the full demo ------------------------------------------
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


@pytest.fixture(scope="module")
def demo_con(tmp_path_factory):
    return build(tmp_path_factory.mktemp("demo"), source="data/demo/Fills.csv")


@pytest.fixture(scope="module")
def ctx(demo_con):
    t = demo_con.execute("select * from marts.fct_trades_enriched").fetchdf()
    t["exit_time"] = pd.to_datetime(t["exit_time"])
    return t


def close(a, b):
    return (pd.isna(a) and pd.isna(b)) or a == pytest.approx(b, rel=1e-9, abs=1e-9)


def test_every_kpi_matches_pandas_on_the_demo(demo_con, ctx):
    kpis = demo_con.execute("select * from marts.mart_kpis").fetchdf().set_index("symbol_scope")
    assert set(kpis.index) == {"ALL", "NQ", "MNQ"}
    for scope in kpis.index:
        t = ctx if scope == "ALL" else ctx[ctx["symbol"] == scope]
        expect = pandas_metrics(t)
        dd, ws, ls = path_stats(t)
        for name, value in expect.items():
            assert close(kpis.loc[scope, name], value), (scope, name)
        assert kpis.loc[scope, "max_drawdown_usd"] == pytest.approx(dd)
        assert (kpis.loc[scope, "max_win_streak"], kpis.loc[scope, "max_loss_streak"]) == (ws, ls)
        assert kpis.loc[scope, "trading_days"] == t["trade_date"].nunique()


def test_equity_curve_matches_numpy(demo_con, ctx):
    c = demo_con.execute(
        "select * from marts.mart_equity_curve where symbol_scope = 'ALL' order by trade_seq"
    ).fetchdf()
    t = ctx.sort_values(["exit_time", "trade_id"])
    assert c["trade_id"].tolist() == t["trade_id"].tolist()
    equity = t["net_pnl"].cumsum().to_numpy()
    assert c["equity"].to_numpy() == pytest.approx(equity)
    peak = np.maximum.accumulate(np.maximum(equity, 0))
    assert c["drawdown_usd"].to_numpy() == pytest.approx(peak - equity)


DIM_COLUMNS = {
    "hour": "hour_et",
    "weekday": "weekday",
    "side": "side",
    "symbol": "symbol",
    "time_bucket": "time_bucket",
    "duration": "duration_bucket",
}


@pytest.mark.parametrize("dimension", DIM_COLUMNS)
def test_dimension_marts_match_pandas(demo_con, ctx, dimension):
    m = demo_con.execute(
        "select * from marts.mart_perf_by_dimension where dimension = ?", [dimension]
    ).fetchdf()
    col = DIM_COLUMNS[dimension]
    for bucket, t in ctx.groupby(col):
        got = m[m["bucket"] == str(bucket)].iloc[0]
        for name, value in pandas_metrics(t).items():
            assert close(got[name], value), (dimension, bucket, name)
    assert len(m) == ctx[col].nunique()
    assert m["share_of_trades"].sum() == pytest.approx(1.0)


def test_vol_regime_dimension_matches_pandas(demo_con, ctx):
    m = demo_con.execute(
        "select * from marts.mart_perf_by_dimension where dimension = 'vol_regime'"
    ).fetchdf()
    for bucket, t in ctx.assign(r=ctx["vol_regime"].fillna("n/a")).groupby("r"):
        got = m[m["bucket"] == bucket].iloc[0]
        assert got["n_trades"] == len(t) and close(got["net_pnl"], t["net_pnl"].sum())


def test_heatmap_matches_pandas(demo_con, ctx):
    m = demo_con.execute("select * from marts.mart_perf_hour_weekday").fetchdf()
    for (wd, hr), t in ctx.groupby(["weekday_num", "hour_et"]):
        got = m[(m["weekday_num"] == wd) & (m["hour_et"] == hr)].iloc[0]
        for name, value in pandas_metrics(t).items():
            assert close(got[name], value), (wd, hr, name)


def test_daily_mart_matches_pandas(demo_con, ctx):
    m = demo_con.execute("select * from marts.mart_daily_performance").fetchdf()
    g = ctx.groupby(["trade_date", "symbol"])
    assert len(m) == len(g)
    for (day, sym), t in g:
        got = m[(m["trade_date"] == day) & (m["symbol"] == sym)].iloc[0]
        assert got["n_trades"] == len(t) and close(got["net_pnl"], t["net_pnl"].sum())
        assert got["n_wins"] == int((t["gross_pnl"] > 0).sum())


def test_date_filter_reaggregates_exactly_from_the_daily_mart(demo_con, ctx):
    """The point of the additive grain: a date filter needs no new SQL logic."""
    lo, hi = date(2026, 3, 1), date(2026, 4, 30)
    got = row(
        demo_con,
        f"""
        select sum(n_wins) * 1.0 / sum(n_trades) as win_rate,
               sum(gross_profit) / abs(sum(gross_loss)) as profit_factor,
               sum(net_pnl) as net_pnl
        from marts.mart_daily_performance where trade_date between '{lo}' and '{hi}'""",
    )
    day = pd.to_datetime(ctx["trade_date"])
    t = ctx[(day >= pd.Timestamp(lo)) & (day <= pd.Timestamp(hi))]
    exp = pandas_metrics(t)
    assert got.win_rate == pytest.approx(exp["win_rate"])
    assert got.profit_factor == pytest.approx(exp["profit_factor"])
    assert got.net_pnl == pytest.approx(exp["net_pnl"])


def test_instruments_seed_still_matches_config():
    seed = pd.read_csv("dbt_project/seeds/instruments.csv").set_index("symbol")
    assert all(seed.loc[s, "multiplier"] == i.multiplier for s, i in INSTRUMENTS.items())
    assert timedelta(0) == timedelta(0)
