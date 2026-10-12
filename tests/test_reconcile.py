from datetime import date

import pandas as pd
import pytest
from scripts.reconcile import main

from trading_analytics.ingest import load_fills
from trading_analytics.ingest.expected import Expected
from trading_analytics.ingest.fill_matcher import match_fills
from trading_analytics.ingest.reconcile import compare, compute_metrics

FIXTURE = "tests/fixtures/tradovate_fills_sample.csv"
# Hand-computed from the fixture: NQ +10.5pt x2 x$20 = 420 gross, 7.0 comm; MNQ -10.25pt x10 x$2
# = -205 gross, 10.0 comm.
YAML_OK = """
settings: {tolerance: 0.01}
net_pnl_total: 198.0
trade_count_total: 2
by_day:
  2030-01-07: {net_pnl: 413.0, trades: 1, win_rate: 1.0, avg_win: 420.0}
by_symbol:
  NQ:  {net_pnl: 413.0, trades: 1, win_rate: 1.0, avg_win: 420.0}
  MNQ: {net_pnl: -215.0, trades: 1, win_rate: 0.0, avg_loss: -205.0}
"""


def trades_from_fixture():
    return match_fills(load_fills(FIXTURE)).trades


def test_fixture_pairs_into_expected_trades():
    t = trades_from_fixture()
    assert t.set_index("symbol")["net_pnl"].to_dict() == {"NQ": 413.0, "MNQ": -215.0}


def test_compute_metrics_basis_changes_win_classification():
    t = pd.DataFrame({"gross_pnl": [1.0, 5.0], "net_pnl": [-1.0, 3.0]})
    assert compute_metrics(t, "gross")["win_rate"] == 1.0
    assert compute_metrics(t, "net")["win_rate"] == 0.5
    assert compute_metrics(t, "gross")["avg_win"] == 3.0  # avg win is always gross


def test_compare_passes_on_matching_totals():
    exp = Expected(net_pnl_total=198.0, trade_count_total=2, by_symbol={"NQ": {"net_pnl": 413.0}})
    assert compare(trades_from_fixture(), exp) == []


def test_compare_reports_each_mismatch_with_diff():
    exp = Expected(
        net_pnl_total=200.0,
        by_day={date(2030, 1, 7): {"trades": 3.0}},
        by_symbol={"MNQ": {"win_rate": 0.5}},
    )
    out = {(m.scope, m.metric): m for m in compare(trades_from_fixture(), exp)}
    assert set(out) == {
        ("TOTAL", "net_pnl"),
        ("day 2030-01-07", "trades"),
        ("symbol MNQ", "win_rate"),
    }
    assert out[("TOTAL", "net_pnl")].actual - out[("TOTAL", "net_pnl")].expected == pytest.approx(
        -2
    )


def test_compare_flags_expected_day_with_no_trades():
    exp = Expected(by_day={date(2031, 1, 1): {"net_pnl": 5.0}})
    (m,) = compare(trades_from_fixture(), exp)
    assert m.actual == 0.0


def test_script_ok_and_mismatch_exit_codes(tmp_path, capsys):
    good = tmp_path / "good.yaml"
    good.write_text(YAML_OK)
    assert main([FIXTURE, str(good)]) == 0
    assert "RECONCILIATION OK" in capsys.readouterr().out

    bad = tmp_path / "bad.yaml"
    bad.write_text(YAML_OK.replace("198.0", "199.0"))
    assert main([FIXTURE, str(bad)]) == 1
    out = capsys.readouterr().out
    assert "RECONCILIATION FAILED" in out and "diff" in out


def test_script_output_never_contains_account(tmp_path, capsys):
    p = tmp_path / "e.yaml"
    p.write_text(YAML_OK.replace("198.0", "0"))
    main([FIXTURE, str(p)])
    assert "TESTACC" not in capsys.readouterr().out


def test_script_missing_file_exit_code_2(tmp_path, capsys):
    assert main([str(tmp_path / "nope.csv"), str(tmp_path / "nope.yaml")]) == 2
