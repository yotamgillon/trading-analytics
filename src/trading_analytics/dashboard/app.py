"""Streamlit dashboard: where do I make money, where do I lose it, and why?

Every number comes from the dbt mart SQL run on the filtered trades (see sqlrender.py); the app
only formats and draws. Run: make dashboard
"""

import pandas as pd
import streamlit as st

from trading_analytics.dashboard import charts, data, insights
from trading_analytics.dashboard.format import condition_table, fmt_money

st.set_page_config(page_title="Trading Analytics", page_icon="📈", layout="wide")


money = fmt_money


def num(x, fmt="{:.2f}") -> str:
    return "n/a" if pd.isna(x) else fmt.format(x)


@st.cache_data(show_spinner="Running the mart SQL on your filters...")
def cached_compute(db, start, end, symbols, accounts, start_balance, combine):
    from pathlib import Path

    return data.compute(Path(db), start, end, symbols, accounts, start_balance, combine)


# ---- sidebar: data source and filters ------------------------------------------------------
st.sidebar.title("Trading Analytics")
private_ready = data.has_marts(data.PRIVATE_DB)
choice = st.sidebar.radio(
    "Data",
    ["Demo (synthetic)", "My data (private)"],
    help="The demo is generated data with no edge built in. Private data never leaves this "
    "machine: it lives in the gitignored data/warehouse/.",
)
use_private = choice.startswith("My")
if use_private and not private_ready:
    st.sidebar.warning(
        "No private warehouse yet. Run `make ingest DATASET=private` then "
        "`make transform DATASET=private`. Showing the demo instead."
    )
    use_private = False
db = data.PRIVATE_DB if use_private else data.ensure_demo_warehouse()

opts = data.filter_options(db)
if opts is None:
    st.info("This warehouse has no trades yet.")
    st.stop()

dates = st.sidebar.date_input(
    "Date range", (opts.min_date, opts.max_date), min_value=opts.min_date, max_value=opts.max_date
)
start, end = (dates[0], dates[-1]) if len(dates) == 2 else (dates[0], opts.max_date)
symbols = st.sidebar.multiselect("Symbol", opts.symbols, default=opts.symbols)
hide = st.sidebar.checkbox("Hide account names", value=use_private)
names = data.mask_accounts(opts.accounts) if hide else {a: a for a in opts.accounts}
chosen = st.sidebar.multiselect(
    "Account", opts.accounts, default=opts.accounts, format_func=lambda a: names[a]
)
combine = st.sidebar.checkbox(
    "Combine selected accounts",
    value=True,
    help="One equity curve and one set of KPIs across the accounts.",
)
balance = st.sidebar.number_input(
    "Starting balance ($)",
    min_value=0.0,
    value=0.0,
    step=1000.0,
    help="0 = equity relative to your first trade. Set it to see drawdown as a % of the account.",
)

st.title("Where do I make money, where do I lose it, and why?")
st.caption(
    (
        "Private data"
        if use_private
        else "Demo data: synthetic trades with no edge, so honest results hover around zero"
    )
    + f" · {start:%b %d, %Y} to {end:%b %d, %Y}"
)

if not symbols or not chosen:
    st.info("Pick at least one symbol and one account.")
    st.stop()
m = cached_compute(str(db), start, end, tuple(symbols), tuple(chosen), balance, combine)
trades = m["fct_trades_enriched"]
if trades.empty:
    st.info("No trades match these filters.")
    st.stop()

kp = m["mart_kpis"]
kp = kp[kp["symbol_scope"] == "ALL"]
accounts_shown = list(kp["account"])
account = (
    accounts_shown[0]
    if len(accounts_shown) == 1
    else st.selectbox("KPIs for account", accounts_shown, format_func=lambda a: names.get(a, a))
)
k = kp[kp["account"] == account].iloc[0]

# ---- KPI cards -----------------------------------------------------------------------------
c = st.columns(5)
c[0].metric("Net P&L", money(k["net_pnl"]), help="After commissions and fees.")
c[1].metric(
    "Trades", f"{int(k['n_trades']):,}", help="A trade is a flat-to-flat position per contract."
)
c[2].metric(
    "Win rate",
    f"{k['win_rate']:.1%}",
    help="Winning trades (gross P&L > 0) divided by all trades; scratches count as neither.",
)
c[3].metric(
    "Profit factor",
    num(k["profit_factor"]),
    help="Gross profit divided by gross loss. Above 1 means winners outweigh losers.",
)
c[4].metric("Expectancy / trade", money(k["expectancy_net"]), help="Average net P&L per trade.")
c = st.columns(5)
c[0].metric("Avg win", money(k["avg_win"]), help="Gross, as most platforms show it.")
c[1].metric("Avg loss", money(k["avg_loss"]), help="Gross (negative).")
dd = money(-k["max_drawdown_usd"]) if k["max_drawdown_usd"] else "$0"
c[2].metric(
    "Max drawdown",
    dd,
    delta=None if pd.isna(k["max_drawdown_pct"]) else f"{k['max_drawdown_pct']:.1%} of peak",
    delta_color="off",
    help="Largest peak-to-trough fall of realised equity, in dollars.",
)
c[3].metric(
    "Costs / gross profit",
    "n/a" if pd.isna(k["costs_pct_of_gross_profit"]) else f"{k['costs_pct_of_gross_profit']:.1%}",
    help="Commissions + fees as a share of the money your winners made.",
)
c[4].metric("Longest streaks", f"{int(k['max_win_streak'])}W / {int(k['max_loss_streak'])}L")

# ---- equity and drawdown -----------------------------------------------------------------
curve = m["mart_equity_curve"]
curve = curve[(curve["symbol_scope"] == "ALL") & (curve["account"] == account)]
st.subheader("Equity curve and drawdown")
st.altair_chart(charts.equity_chart(curve, balance), width="stretch")
st.altair_chart(charts.drawdown_chart(curve), width="stretch")
st.caption("Equity = starting balance + cumulative net P&L, realised when each trade exits.")

# ---- heatmap -------------------------------------------------------------------------------
st.subheader("When do I trade well? Entry hour × weekday")
left, right = st.columns([2, 1])
metric = left.selectbox("Show", list(charts.HEAT_METRICS), index=0)
min_cell = right.slider("Grey out cells with fewer trades than", 1, 30, 5)
cells = m["mart_perf_hour_weekday"]
cells = cells[cells["account"] == account]
st.altair_chart(charts.heatmap(cells, metric, min_cell), width="stretch")
st.caption(
    "Colors saturate at the 90th percentile so one lucky cell cannot dominate; grey cells have "
    "too few trades. Read the trade count in the tooltip before trusting a color."
)

# ---- best / worst conditions ---------------------------------------------------------------
st.subheader("Best and worst conditions")
dims = m["mart_perf_by_dimension"]
dims = dims[dims["account"] == account]
col1, col2 = st.columns(2)
min_n = col1.slider("Minimum trades per condition", 5, 100, insights.MIN_BUCKET_N)
with_dur = col2.checkbox(
    "Include trade duration",
    value=False,
    help="Duration is only known after the trade ends and is tied to the "
    "outcome (a nearer stop is hit sooner), so it is not a condition "
    "you can choose to trade in.",
)
pool = dims[(dims["n_trades"] >= min_n) & (with_dur | dims["is_actionable"])]
if pool.empty:
    st.info("No condition has that many trades yet.")
else:
    t1, t2 = st.columns(2)
    t1.markdown("**Best by expectancy per trade**")
    t1.dataframe(condition_table(pool.nlargest(5, "expectancy_net")), hide_index=True)
    t2.markdown("**Worst by expectancy per trade**")
    t2.dataframe(condition_table(pool.nsmallest(5, "expectancy_net")), hide_index=True)
    st.caption(
        "Ranking many conditions always produces a best and a worst, even for pure noise. "
        "The Insights below test whether the gaps are bigger than chance."
    )

# ---- insights ------------------------------------------------------------------------------
st.subheader("Insights")
acct_trades = trades[trades["account"] == account]
found = insights.generate_insights(acct_trades, k, dims)
icon = {
    "significant": "🟢",
    "not significant": "⚪",
    "descriptive": "🔵",
    "insufficient data": "🟡",
}
for ins in found:
    st.markdown(f"**{icon[ins.evidence]} {ins.headline}**")
    st.markdown(ins.detail)
    st.caption(f"Based on n = {ins.n:,} trades · evidence: {ins.evidence}")

# ---- data quality --------------------------------------------------------------------------
with st.expander("Data quality and caveats"):
    q = m["quality_findings"]
    if q.empty:
        st.success("No data quality issues found.")
    else:
        st.dataframe(
            q[["severity", "check_name", "n", "message"]].rename(
                columns={
                    "severity": "Severity",
                    "check_name": "Check",
                    "n": "Count",
                    "message": "What it means",
                }
            ),
            hide_index=True,
        )
    basis = acct_trades["mae_mfe_basis"].value_counts()
    st.write(
        f"MAE/MFE computed from 1-minute bars for {int(basis.get('bars', 0)):,} of "
        f"{len(acct_trades):,} trades; the rest use fill prices only."
    )
    st.write(
        f"Fills outside their 1-minute bar (after the contract-basis adjustment): "
        f"{int(acct_trades['fills_outside_bar'].sum())}."
    )
    st.write(
        "MNQ trades use NQ bars as a proxy (same index). Volatility regimes are thresholds "
        "from all regular-hours bars in the store, not splits of your trades."
    )

with st.expander("Trades"):
    cols = {
        "trade_id": "Trade",
        "symbol": "Symbol",
        "side": "Direction",
        "qty": "Contracts",
        "entry_time": "Entry (UTC)",
        "exit_time": "Exit (UTC)",
        "gross_pnl": "Gross P&L",
        "net_pnl": "Net P&L",
        "time_bucket": "Time of day",
        "vol_regime": "Volatility regime",
    }
    table = acct_trades[list(cols)].rename(columns=cols)
    st.dataframe(
        table.style.format(
            {"Gross P&L": lambda v: fmt_money(v, 2), "Net P&L": lambda v: fmt_money(v, 2)}
        ),
        hide_index=True,
    )
