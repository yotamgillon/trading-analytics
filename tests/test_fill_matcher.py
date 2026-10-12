import pytest

from tests.helpers import fill, make_fills
from trading_analytics.ingest.fill_matcher import match_fills
from trading_analytics.ingest.schema import TRADE_COLUMNS


def run(*rows):
    return match_fills(make_fills(*rows))


def test_simple_long_round_trip():
    r = run(fill(1, 0, "Buy", 2, 100.0), fill(2, 5, "Sell", 2, 110.0))
    assert list(r.trades.columns) == TRADE_COLUMNS
    t = r.trades.iloc[0]
    assert len(r.trades) == 1
    assert (t["side"], t["qty"], t["entry_price"], t["exit_price"]) == ("Long", 2, 100.0, 110.0)
    assert t["gross_pnl"] == 10 * 2 * 20  # points * qty * NQ multiplier
    assert t["commissions"] == 4.0
    assert t["net_pnl"] == 400 - 4.0
    assert t["trade_id"] == "NQH0-1"
    assert r.open_positions.empty


def test_simple_short_round_trip():
    r = run(fill(1, 0, "Sell", 1, 100.0), fill(2, 5, "Buy", 1, 90.0))
    t = r.trades.iloc[0]
    assert t["side"] == "Short"
    assert t["gross_pnl"] == 10 * 20


def test_losing_trade_is_negative():
    r = run(fill(1, 0, "Buy", 1, 100.0), fill(2, 5, "Sell", 1, 95.0))
    assert r.trades.iloc[0]["gross_pnl"] == -100.0


def test_partial_fills_one_order_entry_average_price():
    r = run(
        fill(1, 0, "Buy", 7, 100.0),
        fill(2, 0, "Buy", 3, 101.0),  # same minute, second partial fill
        fill(3, 5, "Sell", 10, 102.0),
    )
    t = r.trades.iloc[0]
    assert len(r.trades) == 1
    assert t["qty"] == 10 and t["n_fills"] == 3
    assert t["entry_price"] == pytest.approx(100.3)
    assert t["gross_pnl"] == pytest.approx((102 - 100.3) * 10 * 20)


def test_scale_in_and_scale_out_is_one_trade_with_fifo_pnl():
    r = run(
        fill(1, 0, "Buy", 2, 100.0),
        fill(2, 1, "Buy", 2, 110.0),  # scale in
        fill(3, 2, "Sell", 3, 120.0),  # scale out: FIFO takes 2@100 then 1@110
        fill(4, 3, "Sell", 1, 130.0),  # remaining 1@110
    )
    t = r.trades.iloc[0]
    assert len(r.trades) == 1
    assert t["max_position"] == 4 and t["n_fills"] == 4
    assert t["entry_price"] == 105.0
    assert t["exit_price"] == pytest.approx((3 * 120 + 130) / 4)
    fifo_points = 2 * (120 - 100) + 1 * (120 - 110) + 1 * (130 - 110)
    assert t["gross_pnl"] == fifo_points * 20


def test_no_new_trade_while_position_is_reduced_but_not_flat():
    r = run(fill(1, 0, "Buy", 3, 100.0), fill(2, 1, "Sell", 1, 101.0), fill(3, 2, "Sell", 2, 102.0))
    assert len(r.trades) == 1


def test_flip_closes_at_zero_crossing_and_opens_new_trade():
    r = run(
        fill(1, 0, "Buy", 2, 100.0, commission=2.0),
        fill(2, 5, "Sell", 5, 110.0, commission=5.0),  # closes 2 long, opens 3 short
        fill(3, 9, "Buy", 3, 105.0, commission=3.0),
    )
    long_t, short_t = r.trades.iloc[0], r.trades.iloc[1]
    assert (long_t["side"], short_t["side"]) == ("Long", "Short")
    assert long_t["gross_pnl"] == 10 * 2 * 20
    assert short_t["gross_pnl"] == 5 * 3 * 20
    assert short_t["entry_time"] == long_t["exit_time"]
    # the flip fill's commission is split pro rata (2/5 and 3/5)
    assert long_t["commissions"] == pytest.approx(2.0 + 2.0)
    assert short_t["commissions"] == pytest.approx(3.0 + 3.0)
    assert r.open_positions.empty
    assert r.trades["trade_id"].is_unique


def test_flip_that_stays_open_reports_unmatched_position():
    r = run(fill(1, 0, "Buy", 1, 100.0), fill(2, 5, "Sell", 3, 110.0))
    assert len(r.trades) == 1
    o = r.open_positions.iloc[0]
    assert (o["side"], o["open_qty"], o["avg_entry_price"]) == ("Short", 2, 110.0)


def test_open_position_at_end_is_not_invented_as_a_trade():
    r = run(fill(1, 0, "Buy", 2, 100.0))
    assert r.trades.empty
    o = r.open_positions.iloc[0]
    assert (o["contract"], o["side"], o["open_qty"]) == ("NQH0", "Long", 2)


def test_partially_closed_open_position_reports_remaining_lots_only():
    r = run(fill(1, 0, "Buy", 1, 100.0), fill(2, 1, "Buy", 1, 110.0), fill(3, 2, "Sell", 1, 120.0))
    assert r.trades.empty
    o = r.open_positions.iloc[0]
    assert o["open_qty"] == 1 and o["avg_entry_price"] == 110.0  # FIFO: the 100 lot was closed
    assert o["realized_gross_pnl"] == 20 * 20


def test_inactive_fills_excluded_and_listed():
    r = run(
        fill(1, 0, "Buy", 1, 100.0),
        fill(2, 1, "Buy", 5, 50.0, active=False),
        fill(3, 2, "Sell", 1, 101.0),
    )
    assert len(r.trades) == 1 and r.trades.iloc[0]["n_fills"] == 2
    assert r.inactive_fills["fill_id"].tolist() == [2]


def test_contracts_are_never_netted_against_each_other():
    r = run(
        fill(1, 0, "Buy", 1, 100.0, contract="NQH0"),
        fill(2, 1, "Sell", 10, 50.0, contract="MNQH0"),
        fill(3, 2, "Sell", 1, 101.0, contract="NQH0"),
        fill(4, 3, "Buy", 10, 49.0, contract="MNQH0"),
    )
    assert sorted(r.trades["symbol"]) == ["MNQ", "NQ"]
    assert r.trades.set_index("symbol")["gross_pnl"].to_dict() == {
        "NQ": 20.0,
        "MNQ": 1 * 10 * 2.0,
    }


def test_accounts_are_separate_positions():
    r = run(
        fill(1, 0, "Buy", 1, 100.0, account="A"),
        fill(2, 1, "Sell", 1, 101.0, account="B"),  # B opens a short, does not close A
    )
    assert r.trades.empty
    assert len(r.open_positions) == 2


def test_sort_by_time_then_fill_id():
    # same timestamp, input order reversed: fill_id decides, so the buy (id 1) goes first
    r = run(fill(2, 0, "Sell", 1, 101.0), fill(1, 0, "Buy", 1, 100.0))
    assert len(r.trades) == 1 and r.trades.iloc[0]["side"] == "Long"


def test_zero_pnl_scratch_trade():
    r = run(fill(1, 0, "Buy", 1, 100.0), fill(2, 1, "Sell", 1, 100.0))
    t = r.trades.iloc[0]
    assert t["gross_pnl"] == 0 and t["net_pnl"] == -2.0


def test_trade_date_comes_from_exit_fill():
    from datetime import date

    r = run(
        fill(1, 0, "Buy", 1, 100.0, day=date(2030, 1, 7)),
        fill(2, 600, "Sell", 1, 101.0, day=date(2030, 1, 8)),
    )
    assert r.trades.iloc[0]["trade_date"] == date(2030, 1, 8)


@pytest.mark.parametrize(
    "rows",
    [
        [fill(1, 0, "Buy", 2, 100.0), fill(2, 1, "Sell", 2, 103.0)],
        [
            fill(1, 0, "Buy", 2, 100.0, commission=1.75),
            fill(2, 1, "Sell", 5, 99.0, commission=4.4),
            fill(3, 2, "Buy", 3, 98.0, commission=5.25),
        ],
    ],
)
def test_gross_minus_commissions_equals_net(rows):
    t = run(*rows).trades
    assert not t.empty
    assert (t["gross_pnl"] - t["fees"] - t["commissions"] - t["net_pnl"]).abs().max() < 1e-9
    assert (t["gross_pnl"] - t["commissions"] - t["net_pnl"]).abs().max() < 1e-9  # fees are 0


def test_commissions_fully_allocated_across_trades():
    rows = [
        fill(1, 0, "Buy", 2, 100.0, commission=3.5),
        fill(2, 1, "Sell", 5, 110.0, commission=8.75),
        fill(3, 2, "Buy", 3, 105.0, commission=5.25),
    ]
    r = run(*rows)
    assert r.trades["commissions"].sum() == pytest.approx(3.5 + 8.75 + 5.25)
