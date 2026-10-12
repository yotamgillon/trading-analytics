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


def bar_vol(bars):
    """Oracle: std of the previous 30 one-minute changes (>= 15 valid), per bar."""
    closes = bars.set_index("ts")["close"]
    diff = closes.diff()
    diff[closes.index.to_series().diff() > pd.Timedelta(minutes=5)] = np.nan
    return diff.shift(1).rolling(30, min_periods=15).std()


def oracle_thresholds(bars):
    vol = bar_vol(bars)
    m = bars.set_index("ts")["minute_of_day_et"]
    rth = vol[(m >= 570) & (m < 960)].dropna()
    return rth.quantile(1 / 3), rth.quantile(2 / 3), len(rth)


def regime(vol, p33, p67):
    return None if pd.isna(vol) else "low" if vol <= p33 else "mid" if vol <= p67 else "high"


def test_volatility_matches_oracle_and_uses_only_past_bars(ctx, bars):
    vol = bar_vol(bars)
    checked = 0
    for r in ctx.itertuples():
        if pd.isna(r.vol_30m_pts):
            continue
        assert r.vol_30m_pts == pytest.approx(vol[r.entry_time.floor("min")], rel=1e-9)
        checked += 1
    assert checked > 450


def test_regime_thresholds_come_from_all_bars_not_from_trades(wh, ctx, bars):
    p33, p67, n = oracle_thresholds(bars)
    th = q(wh[0], "select * from intermediate.int_vol_regime_thresholds").iloc[0]
    assert th["p33"] == pytest.approx(p33) and th["p67"] == pytest.approx(p67)
    assert th["n_bars"] == n and n > 40_000  # every RTH bar of the store, not 500 trades
    expected = [regime(v, p33, p67) for v in ctx["vol_30m_pts"]]
    assert [x if isinstance(x, str) else None for x in ctx["vol_regime"]] == expected
    assert set(ctx["vol_regime"].dropna()) == {"low", "mid", "high"}
    # trades cluster at the volatile open, so they are NOT spread in equal thirds
    counts = ctx["vol_regime"].value_counts()
    assert counts.max() - counts.min() > 2


def small_sample_warehouse(tmp_path, n_trades=9):
    """First complete trades only (cut where the next trade is not a flip of the last one)."""
    from trading_analytics.quality.pipeline import ingest_file

    raw = pd.read_csv("data/demo/Fills.csv", dtype=str, keep_default_na=False)
    trades = ingest_file("data/demo/Fills.csv").pairing.trades.sort_values("exit_time")
    trades = trades.reset_index(drop=True)
    k = n_trades
    while trades.loc[k, "entry_time"] == trades.loc[k - 1, "exit_time"]:
        k += 1
    cut = raw["_timestamp"] < trades.loc[k, "entry_time"].strftime("%Y-%m-%d %H:%M:%S")
    csv = tmp_path / "Fills.csv"
    raw[cut].to_csv(csv, index=False)
    db = tmp_path / "small.duckdb"
    build_warehouse("demo", db_path=db, fills_path=csv)
    assert run_dbt(db, quiet=True) == 0
    return duckdb.connect(str(db), read_only=True), k


def test_small_sample_is_not_forced_into_thirds(tmp_path, bars):
    con, k = small_sample_warehouse(tmp_path)
    ctx = q(con, "select * from intermediate.int_trade_context order by entry_time")
    assert len(ctx) == k
    p33, p67, _ = oracle_thresholds(bars)
    expected = [regime(v, p33, p67) for v in ctx["vol_30m_pts"]]
    assert list(ctx["vol_regime"]) == expected
    counts = ctx["vol_regime"].value_counts()
    assert not (len(counts) == 3 and counts.nunique() == 1), "forced equal thirds"


def test_dbt_test_catches_forced_thirds(wh):
    """The singular test must flag a tercile split of a small sample (the old behaviour)."""
    con = wh[0]
    sql = open("dbt_project/tests/vol_regime_not_forced_to_thirds.sql").read()
    sql = sql.replace(
        "{{ ref('int_vol_regime_thresholds') }}", "intermediate.int_vol_regime_thresholds"
    )
    # mutate: 9 trades, regimes assigned by ntile over the trades themselves
    con.execute(
        """create or replace temp table forced as
           select * exclude (vol_regime),
                  case ntile(3) over (order by vol_30m_pts) when 1 then 'low' when 2 then 'mid'
                       else 'high' end as vol_regime
           from (select * from intermediate.int_trade_context
                 where vol_30m_pts is not null order by entry_time limit 9)"""
    )
    failing = con.execute(sql.replace("{{ ref('int_trade_context') }}", "forced")).fetchdf()
    assert "small sample forced into equal thirds" in set(failing["problem"])
    healthy = con.execute(
        sql.replace("{{ ref('int_trade_context') }}", "intermediate.int_trade_context")
    ).fetchdf()
    assert healthy.empty


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
