from datetime import date

import pytest

from trading_analytics.ingest.expected import ExpectedFileError, load_expected


def write(tmp_path, text):
    p = tmp_path / "expected.yaml"
    p.write_text(text)
    return p


def test_loads_example_template():
    exp = load_expected("docs/expected.example.yaml")
    assert exp.win_loss_basis == "gross"
    assert date(2030, 1, 7) in exp.by_day
    assert set(exp.by_symbol) == {"NQ", "MNQ"}


def test_defaults(tmp_path):
    exp = load_expected(write(tmp_path, "net_pnl_total: 12.5\n"))
    assert exp.tolerance == 0.01
    assert exp.win_loss_basis == "gross"
    assert exp.net_pnl_total == 12.5
    assert exp.trade_count_total is None


def test_rejects_unknown_metric_typo(tmp_path):
    with pytest.raises(ExpectedFileError, match="netpnl"):
        load_expected(write(tmp_path, "by_symbol:\n  NQ: {netpnl: 1}\n"))


def test_rejects_unknown_top_level_key(tmp_path):
    with pytest.raises(ExpectedFileError, match="Unknown top-level"):
        load_expected(write(tmp_path, "net_pnl: 1\n"))


def test_rejects_bad_basis_and_win_rate(tmp_path):
    with pytest.raises(ExpectedFileError, match="win_loss_basis"):
        load_expected(write(tmp_path, "settings: {win_loss_basis: both}\n"))
    with pytest.raises(ExpectedFileError, match="fraction"):
        load_expected(write(tmp_path, "by_symbol:\n  NQ: {win_rate: 55}\n"))


def test_rejects_bad_date_key(tmp_path):
    with pytest.raises(ExpectedFileError, match="ISO date"):
        load_expected(write(tmp_path, "by_day:\n  tomorrow: {trades: 1}\n"))
