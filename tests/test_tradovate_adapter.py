import warnings

import pandas as pd
import pytest

from trading_analytics.ingest import load_fills
from trading_analytics.ingest.adapters.tradovate_fills import (
    InactiveFillsWarning,
    TradovateFillsAdapter,
)
from trading_analytics.ingest.instruments import UnknownProductError
from trading_analytics.ingest.schema import FILL_COLUMNS, SchemaError

FIXTURE = "tests/fixtures/tradovate_fills_sample.csv"


@pytest.fixture
def raw():
    return pd.read_csv(FIXTURE, dtype=str, keep_default_na=False)


def parse(raw):
    return TradovateFillsAdapter().parse(raw)


def test_load_fills_end_to_end_matches_canonical_schema():
    fills = load_fills(FIXTURE)
    assert list(fills.columns) == FILL_COLUMNS
    assert len(fills) == 5
    assert fills["source_format"].eq("tradovate_fills").all()


def test_side_is_stripped_and_mapped_from_action(raw):
    fills = parse(raw)
    assert fills["side"].tolist() == ["Buy", "Sell", "Buy", "Buy", "Sell"]


def test_timestamp_is_utc_not_local_display_time(raw):
    fills = parse(raw)
    first = fills.iloc[0]["fill_time"]
    assert str(first.tzinfo) == "UTC"
    assert first.hour == 14  # display column says 16:31 (Israel); UTC is the source of truth


def test_dst_shift_in_display_column_does_not_affect_utc(raw):
    # Jan row displays UTC+2, July row displays UTC+3; the parsed UTC times are exact.
    fills = parse(raw)
    jan = fills[fills["fill_id"] == 900000000003].iloc[0]["fill_time"]
    jul = fills[fills["fill_id"] == 900000000005].iloc[0]["fill_time"]
    assert (jan.hour, jul.hour) == (15, 15)


def test_commission_is_per_fill_total_and_fees_zero(raw):
    fills = parse(raw)
    assert fills["commission"].tolist() == [3.5, 3.5, 3.5, 1.5, 5.0]
    assert (fills["fees"] == 0).all()


def test_multiplier_from_config_table(raw):
    fills = parse(raw)
    assert fills.set_index("symbol")["multiplier"].to_dict() == {"NQ": 20.0, "MNQ": 2.0}


def test_partial_fills_share_order_id(raw):
    fills = parse(raw)
    assert fills[fills["order_id"] == 900000000010]["qty"].tolist() == [7, 3]


def test_output_sorted_by_time(raw):
    shuffled = raw.sample(frac=1, random_state=1)
    fills = parse(shuffled)
    assert fills["fill_time"].is_monotonic_increasing


def test_unknown_product_fails(raw):
    raw.loc[0, "Product"] = "XYZ"
    with pytest.raises(UnknownProductError):
        parse(raw)


def test_action_and_bs_mismatch_fails(raw):
    raw.loc[0, "B/S"] = " Sell"
    with pytest.raises(SchemaError, match="B/S"):
        parse(raw)


def test_qty_and_price_mismatch_fail(raw):
    bad_qty = raw.copy()
    bad_qty.loc[0, "Quantity"] = "9"
    with pytest.raises(SchemaError, match="Quantity"):
        parse(bad_qty)
    bad_price = raw.copy()
    bad_price.loc[0, "Price"] = "1.00"
    with pytest.raises(SchemaError, match="Price"):
        parse(bad_price)


def test_duplicate_fill_id_fails(raw):
    raw.loc[1, "_id"] = raw.loc[0, "_id"]
    with pytest.raises(SchemaError, match="Duplicate"):
        parse(raw)


def test_inactive_fill_warns_and_is_flagged(raw):
    raw.loc[2, "_active"] = "false"
    with pytest.warns(InactiveFillsWarning, match="1 inactive"):
        fills = parse(raw)
    assert fills["is_active"].tolist().count(False) == 1


def test_all_active_emits_no_warning(raw):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        parse(raw)


def test_empty_export_fails(raw):
    with pytest.raises(SchemaError, match="no rows"):
        parse(raw.iloc[0:0])
