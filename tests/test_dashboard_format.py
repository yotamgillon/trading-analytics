import pandas as pd
import pytest

from trading_analytics.dashboard import charts
from trading_analytics.dashboard.format import DIMENSION_LABELS, condition_table, fmt_money


@pytest.mark.parametrize(
    ("value", "decimals", "expected"),
    [
        (-68.87, 2, "-$68.87"),
        (68.87, 2, "$68.87"),
        (-1234.5, 0, "-$1,234"),
        (0, 0, "$0"),
        (float("nan"), 0, "n/a"),
    ],
)
def test_negative_money_is_minus_then_dollar(value, decimals, expected):
    assert fmt_money(value, decimals) == expected


def test_condition_table_uses_human_names_and_formats():
    df = pd.DataFrame(
        {
            "dimension": ["vol_regime"],
            "bucket": ["low"],
            "n_trades": [175],
            "win_rate": [0.4171],
            "expectancy_net": [-68.87],
            "profit_factor": [0.93],
            "net_pnl": [-12052.0],
            "is_actionable": [True],
        }
    )
    styler = condition_table(df)
    assert list(styler.data.columns) == [
        "Condition",
        "Bucket",
        "Trades",
        "Win rate",
        "Expectancy",
        "Profit factor",
        "Net P&L",
    ]
    html = styler.to_html()
    assert "Volatility regime" in html and "-$68.87" in html and "42%" in html
    assert "$-" not in html and "vol_regime" not in html
    assert set(DIMENSION_LABELS) >= {"hour", "weekday", "vol_regime", "duration"}


def cells(days=("Monday", "Friday"), hours=(10, 11)):
    return pd.DataFrame(
        [
            {
                "weekday": d,
                "hour_et": h,
                "n_trades": 12,
                "expectancy_net": 5.0,
                "net_pnl": 60.0,
                "win_rate": 0.5,
            }
            for d in days
            for h in hours
        ]
    )


def test_heatmap_always_shows_all_five_weekdays_and_every_hour():
    spec = charts.heatmap(cells(), "Expectancy per trade ($)", 5).to_dict()
    data = spec["datasets"][next(iter(spec["datasets"]))]
    assert {r["weekday"] for r in data} == {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday"}
    assert {r["hour_et"] for r in data} == {9, 10, 11}  # from 9:00 to the last hour traded
    empty = [r for r in data if r["weekday"] == "Tuesday"]
    assert all(r["n_trades"] == 0 for r in empty)


def test_heatmap_hours_are_horizontal_clock_labels_and_cells_are_tall():
    spec = charts.heatmap(cells(), "Expectancy per trade ($)", 5).to_dict()
    x = spec["layer"][0]["encoding"]["x"]["axis"]
    assert x["labelAngle"] == 0 and "':00'" in x["labelExpr"]
    assert spec["height"] >= 5 * 56


def curve(days):
    t = pd.date_range("2026-01-05 15:00", periods=days * 2, freq="12h")
    return pd.DataFrame(
        {
            "exit_time": t,
            "equity": range(len(t)),
            "trade_seq": range(len(t)),
            "net_pnl": 1.0,
            "drawdown_usd": 0.0,
        }
    )


@pytest.mark.parametrize(
    ("days", "every", "fmt"), [(135, "month", "%b %Y"), (30, "week", "%b %d"), (5, "day", "%b %d")]
)
def test_equity_axis_ticks_adapt_but_months_are_consistent(days, every, fmt):
    spec = charts.equity_chart(curve(days), 0).to_dict()
    axis = spec["layer"][1]["encoding"]["x"]["axis"]
    assert axis["tickCount"] == every and axis["format"] == fmt and axis["labelAngle"] == 0
