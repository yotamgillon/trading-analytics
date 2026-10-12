import pandas as pd
import pytest

from trading_analytics.demo import DEFAULT_SEED, generate_demo
from trading_analytics.ingest import detect, load_fills
from trading_analytics.ingest.adapters import TradovateFillsAdapter
from trading_analytics.ingest.fill_matcher import match_fills

REAL_HEADER = (
    "_id,_orderId,_contractId,_timestamp,_tradeDate,_action,_qty,_price,_active,_accountId,"
    "Fill ID,Order ID,Timestamp,Date,Account,B/S,Quantity,Price,_priceFormat,_priceFormatType,"
    "_tickSize,Contract,Product,Product Description,commission"
)


@pytest.fixture(scope="module")
def demo():
    return generate_demo(DEFAULT_SEED)


@pytest.fixture(scope="module")
def parsed(demo, tmp_path_factory):
    path = tmp_path_factory.mktemp("demo") / "Fills.csv"
    demo.raw_fills.to_csv(path, index=False)
    fills = load_fills(path)  # real detection + real adapter
    return fills, match_fills(fills)


def test_raw_export_has_exact_platform_header_and_is_detected(demo):
    assert ",".join(demo.raw_fills.columns) == REAL_HEADER
    assert detect.detect_adapter(demo.raw_fills.columns) is TradovateFillsAdapter


def test_about_500_trades_with_both_products(demo):
    assert len(demo.truth_trades) == 500
    assert set(demo.truth_trades["symbol"]) == {"NQ", "MNQ"}


def test_generation_is_deterministic_within_a_run():
    a, b = generate_demo(7, n_trades=50, n_days=20), generate_demo(7, n_trades=50, n_days=20)
    pd.testing.assert_frame_equal(a.raw_fills, b.raw_fills)
    pd.testing.assert_frame_equal(a.bars_1m, b.bars_1m)


def test_different_seeds_differ():
    a, b = generate_demo(1, n_trades=50, n_days=20), generate_demo(2, n_trades=50, n_days=20)
    assert not a.raw_fills.equals(b.raw_fills)


def test_exercises_partial_fills_scaling_and_flips(demo, parsed):
    fills, result = parsed
    assert fills.groupby("order_id").size().max() >= 2  # partial fills
    assert (result.trades["n_fills"] >= 4).any()  # scale in / out
    assert (fills["is_active"]).all()
    truth = demo.truth_trades
    assert truth["entry_time"].isin(truth["exit_time"]).any()  # flips (reversal at the exit fill)


def test_matcher_recovers_generator_ground_truth(demo, parsed):
    _, result = parsed
    t = result.trades.sort_values("entry_time").reset_index(drop=True)
    truth = demo.truth_trades
    assert result.open_positions.empty
    assert len(t) == len(truth)
    assert (t["entry_time"] == truth["entry_time"]).all()
    assert (t["qty"] == truth["qty"]).all()
    assert (t["gross_pnl"] - truth["gross_pnl"]).abs().max() < 1e-6
    assert (t["commissions"] - truth["commissions"]).abs().max() < 1e-9
    assert ((t["exit_time"] - truth["exit_time"]).dt.total_seconds().abs() < 1).all()


def test_commission_rates_match_platform_convention(parsed):
    fills, _ = parsed
    rate = fills["commission"] / fills["qty"]
    assert rate[fills["symbol"] == "NQ"].eq(1.75).all()
    assert rate[fills["symbol"] == "MNQ"].eq(0.5).all()


def test_fills_ids_increase_with_time(parsed):
    fills, _ = parsed
    assert fills["fill_id"].is_monotonic_increasing
    assert fills["fill_time"].is_monotonic_increasing


def test_display_timestamp_follows_israel_dst(demo):
    raw = demo.raw_fills.assign(_ts=lambda d: pd.to_datetime(d["_timestamp"], utc=True))
    local = pd.to_datetime(raw["Timestamp"], format="%m/%d/%Y %H:%M:%S")
    offset_h = ((local - raw["_ts"].dt.tz_localize(None)).dt.total_seconds() / 3600).round()
    assert set(offset_h) == {2.0, 3.0}  # winter UTC+2, summer UTC+3


def test_bars_are_valid_ohlc_and_cover_every_trade(demo):
    b = demo.bars_1m
    assert (b["high"] >= b[["open", "close", "low"]].max(axis=1)).all()
    assert (b["low"] <= b[["open", "close", "high"]].min(axis=1)).all()
    assert ((b["close"] % 0.25) == 0).all()
    ts = set(b["ts"])
    entry_minutes = demo.truth_trades["entry_time"].dt.floor("min")
    exit_minutes = demo.truth_trades["exit_time"].dt.floor("min")
    assert entry_minutes.isin(ts).all() and exit_minutes.isin(ts).all()
    assert b["symbol"].eq("NQ=F").all()


def test_vix_is_daily_and_plausible(demo):
    v = demo.vix_daily
    assert v["date"].is_unique and v["close"].between(9, 60).all()


def test_demo_contains_no_real_account_markers(demo):
    assert set(demo.raw_fills["Account"]) == {"DEMO"}
    assert set(demo.raw_fills["_accountId"]) == {"10000001"}
