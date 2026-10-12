"""Altair charts. One hue for one series, a blue<->red diverging scale with a gray midpoint
for signed values, hairline grids, tooltips on every mark (the n is always in the tooltip)."""

import altair as alt
import pandas as pd

BLUE, RED, MID = "#2a78d6", "#e34948", "#f0efec"
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


def _base(chart: alt.Chart) -> alt.Chart:
    return (
        chart.configure_axis(grid=True, gridColor="#8887811f", domain=False, tickColor="#8887811f")
        .configure_view(strokeWidth=0)
        .configure_legend(orient="top", title=None)
    )


def equity_chart(curve: pd.DataFrame, start_balance: float) -> alt.Chart:
    d = curve.assign(exit_time=pd.to_datetime(curve["exit_time"]))
    line = (
        alt.Chart(d)
        .mark_line(color=BLUE, strokeWidth=2, interpolate="step-after")
        .encode(
            x=alt.X("exit_time:T", title=None),
            y=alt.Y("equity:Q", title="Equity ($)", scale=alt.Scale(zero=False)),
            tooltip=[
                alt.Tooltip("exit_time:T", title="Exit"),
                alt.Tooltip("trade_seq:Q", title="Trade #"),
                alt.Tooltip("net_pnl:Q", title="Trade net $", format=",.2f"),
                alt.Tooltip("equity:Q", title="Equity $", format=",.2f"),
            ],
        )
    )
    zero = (
        alt.Chart(pd.DataFrame({"y": [start_balance]}))
        .mark_rule(color="#898781", strokeDash=[4, 4])
        .encode(y="y:Q")
    )
    return _base((zero + line).properties(height=260))


def drawdown_chart(curve: pd.DataFrame) -> alt.Chart:
    d = curve.assign(exit_time=pd.to_datetime(curve["exit_time"]), under=-curve["drawdown_usd"])
    area = (
        alt.Chart(d)
        .mark_area(
            color=RED,
            opacity=0.35,
            line={"color": RED, "strokeWidth": 1.5},
            interpolate="step-after",
        )
        .encode(
            x=alt.X("exit_time:T", title=None),
            y=alt.Y("under:Q", title="Drawdown from peak ($)"),
            tooltip=[
                alt.Tooltip("exit_time:T", title="Exit"),
                alt.Tooltip("drawdown_usd:Q", title="Below peak $", format=",.2f"),
            ],
        )
    )
    return _base(area.properties(height=160))


HEAT_METRICS = {
    "Expectancy per trade ($)": ("expectancy_net", ",.2f"),
    "Net P&L ($)": ("net_pnl", ",.0f"),
    "Win rate": ("win_rate", ".0%"),
    "Number of trades": ("n_trades", "d"),
}


def heatmap(cells: pd.DataFrame, metric_label: str, min_n: int) -> alt.Chart:
    col, fmt = HEAT_METRICS[metric_label]
    d = cells.assign(
        shown=cells[col].where(cells["n_trades"] >= min_n),
        note=cells["n_trades"].map(lambda n: "" if n >= min_n else f"fewer than {min_n} trades"),
    )
    if col == "n_trades":
        color = alt.Color(
            "shown:Q", scale=alt.Scale(range=[MID, BLUE], interpolate="rgb"), title=metric_label
        )
    elif col == "win_rate":
        color = alt.Color(
            "shown:Q",
            scale=alt.Scale(
                domain=[0.3, 0.5, 0.7], range=[RED, MID, BLUE], clamp=True, interpolate="rgb"
            ),
            title=metric_label,
            legend=alt.Legend(format=".0%"),
        )
    else:
        # Saturate at the 90th percentile of |value| so one lucky cell cannot wash out the rest.
        cap = float(d["shown"].abs().quantile(0.9)) if d["shown"].notna().any() else 1.0
        cap = max(cap, 1e-9)
        color = alt.Color(
            "shown:Q",
            scale=alt.Scale(
                domain=[-cap, 0, cap], range=[RED, MID, BLUE], clamp=True, interpolate="rgb"
            ),
            title=metric_label,
        )
    base = alt.Chart(d).encode(
        x=alt.X("hour_et:O", title="Entry hour (ET)"),
        y=alt.Y("weekday:N", sort=WEEKDAYS, title=None),
    )
    cells_layer = base.mark_rect(stroke="#fcfcfb", strokeWidth=2).encode(
        color=color,
        tooltip=[
            alt.Tooltip("weekday:N", title="Day"),
            alt.Tooltip("hour_et:O", title="Hour ET"),
            alt.Tooltip("n_trades:Q", title="Trades"),
            alt.Tooltip(f"{col}:Q", title=metric_label, format=fmt),
            alt.Tooltip("note:N", title=""),
        ],
    )
    grey = base.mark_rect(
        stroke="#fcfcfb", strokeWidth=2, color="#898781", opacity=0.12
    ).transform_filter(alt.datum.n_trades < min_n)
    return _base((cells_layer + grey).properties(height=230))
