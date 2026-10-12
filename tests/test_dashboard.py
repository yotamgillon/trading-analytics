"""Dashboard data layer, insights and the Streamlit app, tested offline on synthetic data."""

import shutil

import duckdb
import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from tests.oracle import close, pandas_metrics, path_stats
from trading_analytics.dashboard import data, insights
from trading_analytics.dashboard.sqlrender import build_filtered_marts
from trading_analytics.dbt_runner import run_dbt
from trading_analytics.warehouse import build_warehouse


@pytest.fixture(scope="module")
def demo_db(tmp_path_factory):
    db = tmp_path_factory.mktemp("dash") / "demo.duckdb"
    build_warehouse("demo", db_path=db)
    assert run_dbt(db, quiet=True) == 0
    return db


@pytest.fixture
def con(demo_db):
    c = duckdb.connect(str(demo_db), read_only=True)
    c.execute("SET TimeZone = 'UTC'")
    yield c
    c.close()


def sorted_frame(df):
    return df.sort_values(list(df.columns), kind="stable").reset_index(drop=True)


# ---- the dashboard runs the SAME SQL as the marts ---------------------------------------------
@pytest.mark.parametrize(
    "mart",
    [
        "mart_equity_curve",
        "mart_streaks",
        "mart_kpis",
        "mart_perf_by_dimension",
        "mart_perf_hour_weekday",
        "mart_daily_performance",
    ],
)
def test_unfiltered_dashboard_marts_equal_the_dbt_built_marts(con, mart):
    live = build_filtered_marts(con, "true", [])[mart]
    built = con.execute(f"select * from marts.{mart}").df()
    pd.testing.assert_frame_equal(sorted_frame(live), sorted_frame(built), check_dtype=False)


def test_filters_change_which_trades_not_how_metrics_are_computed(con):
    where = "trade_date between ? and ? and symbol in (?)"
    params = ["2026-03-01", "2026-05-31", "NQ"]
    out = build_filtered_marts(con, where, params)
    t = out["fct_trades_enriched"]
    assert len(t) > 20 and set(t["symbol"]) == {"NQ"}
    k = out["mart_kpis"].set_index("symbol_scope").loc["ALL"]
    for name, value in pandas_metrics(t).items():
        assert close(k[name], value), name
    dd, ws, ls = path_stats(t)
    assert k["max_drawdown_usd"] == pytest.approx(dd)
    assert (k["max_win_streak"], k["max_loss_streak"]) == (ws, ls)
    assert out["mart_equity_curve"].query("symbol_scope == 'ALL'")["equity"].iloc[-1] == (
        pytest.approx(t["net_pnl"].sum())
    )


def test_filtered_curve_restarts_from_zero_at_the_filter_start(con):
    out = build_filtered_marts(con, "trade_date >= ?", ["2026-06-01"])
    first = out["mart_equity_curve"].query("symbol_scope == 'ALL'").sort_values("trade_seq").iloc[0]
    assert first["equity"] == pytest.approx(first["net_pnl"])


def test_starting_balance_enables_drawdown_percent(con):
    none = build_filtered_marts(con, "true", [])["mart_kpis"].sort_values("symbol_scope")
    some = build_filtered_marts(con, "true", [], start_balance=50_000)["mart_kpis"]
    some = some.sort_values("symbol_scope")
    assert none["max_drawdown_pct"].isna().all() and some["max_drawdown_pct"].notna().all()
    assert none["max_drawdown_usd"].tolist() == pytest.approx(some["max_drawdown_usd"].tolist())


def test_empty_selection_gives_empty_marts_not_errors(con):
    out = build_filtered_marts(con, "symbol = ?", ["XYZ"])
    assert out["fct_trades_enriched"].empty and out["mart_kpis"].empty


def test_combining_accounts_merges_curves_and_kpis(tmp_path):
    raw = pd.read_csv("data/demo/Fills.csv", dtype=str, keep_default_na=False)
    odd = pd.to_datetime(raw["_tradeDate"]).dt.dayofyear % 2 == 1
    raw.loc[odd, "Account"] = "ACC_B"  # whole days go to the second account
    csv = tmp_path / "Fills.csv"
    raw.to_csv(csv, index=False)
    db = tmp_path / "two.duckdb"
    build_warehouse("demo", db_path=db, fills_path=csv)
    assert run_dbt(db, quiet=True) == 0
    con = duckdb.connect(str(db), read_only=True)
    separate = build_filtered_marts(con, "true", [], combine_accounts=False)["mart_kpis"]
    combined = build_filtered_marts(con, "true", [], combine_accounts=True)["mart_kpis"]
    sep_all = separate[separate["symbol_scope"] == "ALL"]
    com_all = combined[combined["symbol_scope"] == "ALL"]
    assert len(sep_all) == 2 and list(com_all["account"]) == ["All accounts"]
    assert com_all["n_trades"].iloc[0] == sep_all["n_trades"].sum() == 500
    assert com_all["net_pnl"].iloc[0] == pytest.approx(sep_all["net_pnl"].sum())
    assert data.mask_accounts(["ACC_B", "DEMO"]) == {"ACC_B": "Account A", "DEMO": "Account B"}
    con.close()


# ---- insights ---------------------------------------------------------------------------------
def fake_trades(n=300, seed=0, edge_hour=None, edge=0.0):
    """Trades with the columns the insights read. net P&L is zero-mean fat-tailed noise."""
    rng = np.random.default_rng(seed)
    pnl = rng.standard_t(3, n) * 150
    hour = rng.choice([9, 10, 11, 12, 13, 14, 15], n)
    if edge_hour is not None:
        pnl = pnl + np.where(hour == edge_hour, edge, 0)
    return pd.DataFrame(
        {
            "net_pnl": pnl,
            "gross_pnl": pnl + 3.5,
            "commissions": 3.5,
            "fees": 0.0,
            "duration_min": rng.exponential(5, n),
            "hour_et": hour,
            "weekday": rng.choice(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"], n),
            "time_bucket": rng.choice(["Open", "Morning", "Midday", "Afternoon"], n),
            "session": "RTH",
            "vol_regime": rng.choice(["low", "mid", "high"], n),
            "vix_regime": rng.choice(["< 15", "15-20", "20-25"], n),
            "side": rng.choice(["Long", "Short"], n),
            "symbol": rng.choice(["NQ", "MNQ"], n),
            "dist_from_open_signed_pts": rng.normal(0, 50, n),
            "is_win": pnl + 3.5 > 0,
            "is_loss": pnl + 3.5 < 0,
        }
    )


def kpi_row(t, max_loss_streak=5):
    m = pandas_metrics(t)
    m.update(
        gross_profit=t.loc[t["gross_pnl"] > 0, "gross_pnl"].sum(),
        max_loss_streak=max_loss_streak,
    )
    return pd.Series(m)


def dims_for(t):
    rows = []
    for dim, labels in insights.labels_for(t).items():
        for bucket, g in t.groupby(labels):
            rows.append(
                {"dimension": dim, "bucket": bucket, "is_actionable": True, **pandas_metrics(g)}
            )
    return pd.DataFrame(rows)


def run_insights(t, **kw):
    return insights.generate_insights(t, kpi_row(t, **kw), dims_for(t))


def test_labels_match_the_sql_mart_buckets(con):
    t = build_filtered_marts(con, "true", [])
    mart = t["mart_perf_by_dimension"]
    for dim, labels in insights.labels_for(t["fct_trades_enriched"]).items():
        sql_counts = mart[mart["dimension"] == dim].set_index("bucket")["n_trades"].to_dict()
        assert labels.value_counts().to_dict() == sql_counts, dim


def test_noise_is_reported_as_noise():
    found = run_insights(fake_trades(400))
    assert 3 <= len(found) <= 5
    assert all(i.n > 0 for i in found)
    by_kind = {i.kind: i for i in found}
    assert by_kind["edge"].evidence == "not significant"
    assert by_kind["best"].evidence == "not significant"
    assert "chance" in by_kind["best"].detail


def test_a_planted_edge_is_found_and_called_significant():
    found = run_insights(fake_trades(600, edge_hour=10, edge=250))
    best = next(i for i in found if i.kind == "best")
    assert best.evidence == "significant" and "10" in best.headline


def test_best_and_worst_ignore_duration_even_if_it_looks_great():
    t = fake_trades(300)
    dims = dims_for(t)
    dur = dims.iloc[:2].assign(
        dimension="duration",
        bucket=["< 1 min", "30+ min"],
        is_actionable=False,
        expectancy_net=[9999.0, -9999.0],
        n_trades=100,
    )
    found = insights.generate_insights(t, kpi_row(t), pd.concat([dims, dur]))
    assert all("duration" not in (i.headline + i.detail) for i in found)


def test_tiny_samples_degrade_gracefully():
    t = fake_trades(9)
    found = run_insights(t)
    assert 1 <= len(found) <= 5
    assert {i.kind: i.evidence for i in found}["conditions"] == "insufficient data"
    assert next(i for i in found if i.kind == "edge").n == 9
    assert insights.generate_insights(t.iloc[0:0], kpi_row(t), dims_for(t)) == []


def test_clustered_losses_are_flagged_but_normal_streaks_are_not():
    t = fake_trades(300)
    normal = next(i for i in run_insights(t, max_loss_streak=6) if i.kind == "streaks")
    assert normal.evidence == "not significant"
    odd = next(i for i in run_insights(t, max_loss_streak=40) if i.kind == "streaks")
    assert odd.evidence == "significant"


def test_false_alarm_rate_on_pure_noise_is_controlled():
    """Scanning 9 dimensions must not manufacture 'significant' conditions."""
    flagged = 0
    for seed in range(40):
        found = run_insights(fake_trades(250, seed=seed))
        flagged += any(i.evidence == "significant" for i in found if i.kind in ("best", "worst"))
    assert flagged <= 4  # nominal 5% per run, Bonferroni makes it smaller


def test_signflip_test_detects_a_real_mean():
    from trading_analytics.stats import signflip_pvalue

    rng = np.random.default_rng(1)
    assert signflip_pvalue(rng.normal(0, 1, 200)) > 0.05
    assert signflip_pvalue(rng.normal(0.5, 1, 200)) < 0.01


# ---- the app ----------------------------------------------------------------------------------
@pytest.fixture
def app(demo_db, tmp_path, monkeypatch):
    monkeypatch.setattr(data, "DEMO_DB", demo_db)
    monkeypatch.setattr(data, "PRIVATE_DB", tmp_path / "absent.duckdb")
    return AppTest.from_file("src/trading_analytics/dashboard/app.py", default_timeout=180)


def test_app_renders_kpis_charts_and_insights(app):
    at = app.run()
    assert not at.exception
    labels = {m.label for m in at.metric}
    assert {
        "Net P&L",
        "Trades",
        "Win rate",
        "Profit factor",
        "Expectancy / trade",
        "Max drawdown",
    } <= labels
    assert next(m for m in at.metric if m.label == "Trades").value == "500"
    shown = [m.value for m in at.markdown if "Based on" in m.value or m.value.startswith("**")]
    assert any("n = " in c.value for c in at.caption)
    assert len([c for c in at.caption if "Based on n =" in c.value]) in (3, 4, 5)
    assert shown


def test_app_filters_reduce_the_trade_count(app):
    at = app.run()
    symbols = next(w for w in at.sidebar.multiselect if w.label == "Symbol")
    symbols.set_value(["NQ"])
    at.run()
    assert not at.exception
    assert next(m for m in at.metric if m.label == "Trades").value == "152"


def test_private_toggle_falls_back_to_demo_when_no_private_warehouse(app):
    at = app.run()
    at.sidebar.radio[0].set_value("My data (private)")
    at.run()
    assert not at.exception
    assert any("No private warehouse" in w.value for w in at.sidebar.warning)
    assert any("Demo data" in c.value for c in at.caption)


def test_private_toggle_uses_the_private_warehouse_and_masks_accounts(
    demo_db, tmp_path, monkeypatch
):
    private = tmp_path / "private.duckdb"
    shutil.copy(demo_db, private)  # stand-in for a real private warehouse
    monkeypatch.setattr(data, "DEMO_DB", demo_db)
    monkeypatch.setattr(data, "PRIVATE_DB", private)
    at = AppTest.from_file("src/trading_analytics/dashboard/app.py", default_timeout=180).run()
    at.sidebar.radio[0].set_value("My data (private)")
    at.run()
    assert not at.exception
    assert any("Private data" in c.value for c in at.caption)
    acct = next(w for w in at.sidebar.multiselect if w.label == "Account")
    assert acct.value == ["DEMO"]  # the filter value is the real name...
    assert at.sidebar.checkbox[0].value is True  # ...but names are hidden by default for private
    page_text = " ".join(m.value for m in at.markdown) + " ".join(c.value for c in at.caption)
    assert "DEMO" not in page_text


def test_insight_text_escapes_dollars_so_money_is_not_rendered_as_latex(app):
    at = app.run()
    costs = next(m.value for m in at.markdown if "That is about" in m.value)
    assert "\\$" in costs  # escaped; two raw $ in one paragraph would be typeset as math
    assert "$" not in costs.replace("\\$", "")
