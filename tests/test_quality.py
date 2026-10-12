import pandas as pd
import pytest
from scripts.quality_report import main as quality_main

from trading_analytics.demo import DEFAULT_SEED, generate_demo
from trading_analytics.demo.defects import inject_defects
from trading_analytics.quality.findings import QualityError, QualityReport
from trading_analytics.quality.pipeline import ingest_frame
from trading_analytics.quality.timezone import add_local_times, session_trade_date

FIXTURE = "tests/fixtures/tradovate_fills_sample.csv"


@pytest.fixture(scope="module")
def raw_demo():
    return generate_demo(DEFAULT_SEED).raw_fills


@pytest.fixture(scope="module")
def dirty(raw_demo):
    raw, expected = inject_defects(raw_demo)
    return ingest_frame(raw), expected, raw


def by_check(result):
    return {f.check: f for f in result.report.findings}


def test_clean_demo_has_no_fixes_or_warnings(raw_demo):
    r = ingest_frame(raw_demo)
    assert r.report.clean and r.report.rows_raw == r.report.rows_clean == len(raw_demo)
    assert len(r.pairing.trades) == 500


def test_each_injected_defect_is_caught_with_exact_count(dirty):
    result, expected, _ = dirty
    found = by_check(result)
    for check, n in expected.items():
        assert found[check].count == n, check


def test_fixed_rows_are_excluded_and_row_accounting_adds_up(dirty):
    result, _, raw = dirty
    # 2 duplicates dropped, 1 blank quarantined, 2 bad prices removed
    assert result.report.rows_raw == len(raw)
    assert result.report.rows_clean == len(raw) - 2 - 1 - 2
    assert len(result.quarantined) == 1
    assert result.fills["fill_id"].is_unique
    assert not result.pairing.inactive_fills.empty
    assert (~result.fills["is_active"]).sum() == 1


def test_excluding_fills_raises_a_pairing_warning(dirty):
    result, _, _ = dirty
    assert "excluded_fills_break_pairing" in by_check(result)
    assert "unmatched_open_position" in by_check(result)


def test_report_lists_fill_ids_but_never_accounts(dirty):
    result, _, _ = dirty
    text = result.report.render() + result.report.render(markdown=True)
    assert "DEMO" not in text and "10000001" not in text
    assert "800000" in text  # fill ids are shown so the user can find the row


def test_conflicting_duplicate_ids_are_rejected_not_guessed(raw_demo):
    bad = pd.concat([raw_demo, raw_demo.iloc[[0]].assign(_price="1.0", Price="1.00")])
    with pytest.raises(QualityError, match="share an id"):
        ingest_frame(bad)


def test_fixture_is_clean():
    raw = pd.read_csv(FIXTURE, dtype=str, keep_default_na=False)
    r = ingest_frame(raw)
    assert r.report.clean and len(r.pairing.trades) == 2


def test_weekend_trade_date_and_wrong_trade_date_are_warned():
    raw = pd.read_csv(FIXTURE, dtype=str, keep_default_na=False)
    raw.loc[0, "_tradeDate"] = "2030-01-05"  # a Saturday, and not the session of the fill
    found = by_check(ingest_frame(raw))
    assert found["non_trading_day"].count == 1
    assert found["trade_date_mismatch"].count == 1


def test_inconsistent_order_is_warned():
    raw = pd.read_csv(FIXTURE, dtype=str, keep_default_na=False)
    raw.loc[3, "_orderId"] = raw.loc[2, "_orderId"] = "900000000010"
    raw.loc[3, "Order ID"] = raw.loc[2, "Order ID"] = "900000000010"
    raw.loc[3, ["_action", "B/S"]] = ["1", " Sell"]
    found = by_check(ingest_frame(raw))
    assert found["inconsistent_order"].count == 1


def test_display_time_check_catches_a_utc_parsing_problem():
    raw = pd.read_csv(FIXTURE, dtype=str, keep_default_na=False)
    raw.loc[0, "Timestamp"] = "01/07/2030 14:31:05"  # looks like UTC was shown, not Israel time
    assert by_check(ingest_frame(raw))["display_time_mismatch"].count == 1


def test_report_markdown_and_empty_rendering():
    r = QualityReport(rows_raw=3, rows_clean=3)
    assert "No issues found" in r.render() and "No issues found" in r.render(markdown=True)


# --- timezone normalisation ---------------------------------------------------------------
def utc(s):
    return pd.Series(pd.to_datetime([s], utc=True))


def hours(df, col):
    return {
        "chicago": df[f"{col}_exchange"].iloc[0].hour,
        "et": df[f"{col}_et"].iloc[0].hour,
        "israel": df[f"{col}_israel"].iloc[0].hour,
    }


def test_three_clocks_in_normal_season():
    df = add_local_times(pd.DataFrame({"t": utc("2030-01-15 14:30")}), "t")
    assert hours(df, "t") == {"chicago": 8, "et": 9, "israel": 16}  # winter: ET+7h = Israel


def test_us_and_israel_dst_dates_differ():
    # 2026: US DST began Mar 8, Israel DST began Mar 27 -> the gap shrinks to 6h in between.
    between = add_local_times(pd.DataFrame({"t": utc("2026-03-16 13:30")}), "t")
    assert hours(between, "t") == {"chicago": 8, "et": 9, "israel": 15}
    after = add_local_times(pd.DataFrame({"t": utc("2026-04-06 13:30")}), "t")
    assert hours(after, "t") == {"chicago": 8, "et": 9, "israel": 16}
    # 2026 Oct: Israel DST ends Oct 25 and US DST ends Nov 1 -> gap is 6h in between again.
    odd = add_local_times(pd.DataFrame({"t": utc("2026-10-28 13:30")}), "t")
    assert hours(odd, "t") == {"chicago": 8, "et": 9, "israel": 15}


def test_session_trade_date_rolls_at_1800_et():
    t = pd.Series(
        pd.to_datetime(["2030-01-15 22:59", "2030-01-15 23:00", "2030-01-13 23:00"], utc=True)
    )  # 17:59 ET, 18:00 ET, Sunday 18:00 ET
    assert [d.isoformat() for d in session_trade_date(t)] == [
        "2030-01-15",
        "2030-01-16",
        "2030-01-14",
    ]


def test_quality_script_prints_report(capsys):
    assert quality_main(["data/demo/Fills.csv"]) == 0
    assert "500 flat-to-flat trades" in capsys.readouterr().out
