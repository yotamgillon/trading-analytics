import pandas as pd
import pytest

from trading_analytics.ingest import detect
from trading_analytics.ingest.adapters import TradovateFillsAdapter

FIXTURE = "tests/fixtures/tradovate_fills_sample.csv"


def test_detects_tradovate_from_real_header():
    headers = pd.read_csv(FIXTURE, nrows=0).columns
    assert detect.detect_adapter(headers) is TradovateFillsAdapter


def test_detection_ignores_header_whitespace():
    assert detect.detect_adapter([" _orderId", "Fill ID ", "_timestamp"]) is TradovateFillsAdapter


def test_unknown_format_lists_supported():
    with pytest.raises(detect.UnknownFormatError, match="tradovate_fills"):
        detect.detect_adapter(["Trade #", "Entry", "Exit"])


def test_ambiguous_format(monkeypatch):
    class Twin(TradovateFillsAdapter):
        name = "twin"

    monkeypatch.setattr(detect, "ADAPTERS", [TradovateFillsAdapter, Twin])
    with pytest.raises(detect.AmbiguousFormatError):
        detect.detect_adapter(TradovateFillsAdapter.signature)
