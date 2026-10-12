"""End-to-end: demo CSV -> warehouse -> dbt build, checked against independent pandas oracles."""

import duckdb
import numpy as np
import pandas as pd
import pytest
from scripts.transform import run_dbt

from trading_analytics.ingest.instruments import INSTRUMENTS
from trading_analytics.warehouse import build_warehouse


@pytest.fixture(scope="module")
def wh(tmp_path_factory):
    db = tmp_path_factory.mktemp("wh") / "demo.duckdb"
    summary = build_warehouse("demo", db_path=db)
    assert run_dbt(db, quiet=True) == 0, "dbt build (models + tests) must pass on the demo"
    con = duckdb.connect(str(db), read_only=True)
    con.execute("SET TimeZone = 'UTC'")
    yield con, summary
    con.close()


def q(con, sql):
    return con.execute(sql).fetchdf()


@pytest.fixture(scope="module")
def ctx(wh):
    return q(wh[0], "select * from intermediate.int_trade_context order by entry_time")


@pytest.fixture(scope="module")
def bars(wh):
    return q(wh[0], "select * from staging.stg_bars_1m order by ts")


def test_every_trade_is_kept_exactly_once(wh, ctx):
    assert len(ctx) == wh[1].n_trades == 500
    assert ctx["trade_id"].is_unique


def test_seed_matches_python_instrument_config():
    seed = pd.read_csv("dbt_project/seeds/instruments.csv").set_index("symbol")
    for sym, inst in INSTRUMENTS.items():
        assert seed.loc[sym, "multiplier"] == inst.multiplier
        assert seed.loc[sym, "tick_size"] == inst.tick_size


def test_mnq_uses_nq_bars_as_proxy(wh):
    df = q(wh[0], "select symbol, bar_symbol from staging.stg_fills group by all")
    assert dict(zip(df["symbol"], df["bar_symbol"], strict=True)) == {"NQ": "NQ=F", "MNQ": "NQ=F"}


def test_clocks_and_calendar_columns(ctx):
    assert ctx["session"].eq("RTH").all()  # the demo trades inside regular hours
    assert ctx["hour_et"].between(9, 15).all()
    et = ctx["entry_time"].dt.tz_convert("America/New_York")
    assert (ctx["weekday_num"] == et.dt.dayofweek + 1).all()
    assert (ctx["hour_et"] == et.dt.hour).all()
    il = ctx["entry_time"].dt.tz_convert("Asia/Jerusalem").dt.tz_localize(None)
    assert (pd.to_datetime(ctx["entry_time_israel"]) == il).all()


def test_time_bucket_boundaries(wh):
    con = wh[0]
    rows = q(con, "select bucket, start_minute, end_minute from staging.time_buckets")
    pick = lambda m: rows[(rows.start_minute <= m) & (m < rows.end_minute)].bucket.iloc[0]  # noqa: E731
    assert pick(569) == "Pre-market" and pick(570).startswith("Open")
    assert pick(629).startswith("Open") and pick(630).startswith("Morning")
    assert pick(959).startswith("Close") and pick(960) == "Post-market"


def test_duration_buckets(ctx):
    edges = {"< 1 min": (0, 1), "1-3 min": (1, 3), "3-10 min": (3, 10), "10-30 min": (10, 30)}
    for label, (lo, hi) in edges.items():
        d = ctx.loc[ctx["duration_bucket"] == label, "duration_min"]
        assert d.empty or ((d >= lo) & (d < hi)).all()
    assert (ctx.loc[ctx["duration_bucket"] == "30+ min", "duration_min"] >= 30).all()


def test_dist_from_open_matches_oracle(ctx, bars):
    open_by_day = (
        bars[bars["minute_of_day_et"] == 570].set_index("session_date_et")["open"].to_dict()
    )
    open_at = bars.set_index("ts")["open"]
    for r in ctx.itertuples():
        expect = open_at[r.entry_time.floor("min")] - open_by_day[r.entry_date_et]
        assert r.dist_from_open_pts == pytest.approx(expect)
        sign = 1 if r.side == "Long" else -1
        assert r.dist_from_open_signed_pts == pytest.approx(expect * sign)


def test_volatility_matches_oracle_and_uses_only_past_bars(ctx, bars):
    closes = bars.set_index("ts")["close"]
    diff = closes.diff()
    diff[closes.index.to_series().diff() > pd.Timedelta(minutes=5)] = np.nan
    checked = 0
    for r in ctx.itertuples():
        if pd.isna(r.vol_30m_pts):
            continue
        before = diff[diff.index < r.entry_time.floor("min")].iloc[-30:]
        assert r.vol_30m_pts == pytest.approx(before.std(ddof=1), rel=1e-9)
        checked += 1
    assert checked > 450
    assert set(ctx["vol_regime"].dropna()) == {"low", "mid", "high"}
    counts = ctx["vol_regime"].value_counts()
    assert counts.max() - counts.min() <= 2  # terciles


def test_vix_is_previous_day_close_never_same_day(wh, ctx):
    vix = q(wh[0], "select * from staging.stg_vix").set_index("vix_date")["vix_close"]
    for r in ctx.head(60).itertuples():
        prev = vix[vix.index < r.entry_date_et]
        expect = prev.iloc[-1] if len(prev) else np.nan
        assert (pd.isna(r.vix_prev_close) and pd.isna(expect)) or r.vix_prev_close == expect


def test_mae_mfe_match_oracle(wh, ctx, bars):
    fills = q(wh[0], "select * from staging.stg_fills where is_active")
    by_ts = bars.set_index("ts")
    for r in ctx.itertuples():
        entry_min, exit_min = r.entry_time.floor("min"), r.exit_time.floor("min")
        window = by_ts[(by_ts.index > entry_min) & (by_ts.index <= exit_min)]
        mine = fills[
            (fills.account == r.account)
            & (fills.contract == r.contract)
            & (fills.fill_time >= r.entry_time)
            & (fills.fill_time <= r.exit_time)
        ]["price"]
        hi = max([r.entry_price, r.exit_price, *mine, *window["high"]])
        lo = min([r.entry_price, r.exit_price, *mine, *window["low"]])
        mfe, mae = (
            (hi - r.entry_price, r.entry_price - lo)
            if r.side == "Long"
            else (r.entry_price - lo, hi - r.entry_price)
        )
        assert r.mfe_pts == pytest.approx(mfe) and r.mae_pts == pytest.approx(mae)
        assert r.mae_pts >= 0 and r.mfe_pts >= 0
        assert r.mae_mfe_basis == ("bars" if len(window) else "fills_only")


def test_realised_move_is_inside_the_excursions(ctx):
    sign = np.where(ctx["side"] == "Long", 1, -1)
    move = (ctx["exit_price"] - ctx["entry_price"]) * sign
    assert (ctx["mfe_pts"] >= move - 1e-9).all()
    assert (ctx["mae_pts"] >= -move - 1e-9).all()


def test_demo_fills_all_sit_inside_their_bars(wh):
    status = q(wh[0], "select status, count(*) n from intermediate.int_fill_bar_check group by 1")
    assert dict(zip(status["status"], status["n"], strict=True)) == {"ok": wh[1].n_fills}


# --- the fill-vs-bar check must catch real problems and tolerate the contract basis ---------
def rebuild_with(tmp_path, mutate):
    raw = pd.read_csv("data/demo/Fills.csv", dtype=str, keep_default_na=False)
    raw = mutate(raw)
    csv = tmp_path / "Fills.csv"
    raw.to_csv(csv, index=False)
    db = tmp_path / "w.duckdb"
    build_warehouse("demo", db_path=db, fills_path=csv)
    assert run_dbt(db, quiet=True) == 0
    con = duckdb.connect(str(db), read_only=True)
    return con


def shift(raw, mask, pts):
    for col, fmt in (("_price", str), ("Price", lambda p: f"{p:.2f}")):
        raw.loc[mask, col] = (raw.loc[mask, col].astype(float) + pts).map(fmt)
    return raw


def test_one_bad_print_is_flagged(tmp_path):
    def mutate(raw):
        day = raw["_tradeDate"] == raw["_tradeDate"].iloc[40]
        target = raw[day].index[2]
        return shift(raw, raw.index == target, 120.0)

    con = rebuild_with(tmp_path, mutate)
    out = q(con, "select status, count(*) n from intermediate.int_fill_bar_check group by 1")
    assert dict(zip(out["status"], out["n"], strict=True)).get("outside_bar") == 1
    assert q(con, "select sum(fills_outside_bar) s from intermediate.int_trade_context").s[0] == 1


def test_a_constant_contract_basis_is_estimated_and_tolerated(tmp_path):
    def mutate(raw):  # NQZ6-style basis: one contract trades 40 points above the continuous bars
        return shift(raw, raw["Contract"] == "NQH6", 40.0)

    con = rebuild_with(tmp_path, mutate)
    basis = q(
        con, "select contract, median(basis_pts) b from intermediate.int_fill_bar_check group by 1"
    ).set_index("contract")["b"]
    assert abs(basis["NQH6"] - 40) < 8 and abs(basis["MNQH6"]) < 1e-9
    share = q(con, "select avg((status='outside_bar')::int) s from intermediate.int_fill_bar_check")
    assert share.s[0] < 0.10
