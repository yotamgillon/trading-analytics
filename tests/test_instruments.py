import pytest

from trading_analytics.ingest.instruments import UnknownProductError, get_instrument


@pytest.mark.parametrize(
    ("symbol", "mult", "tick_value"),
    [("NQ", 20, 5.0), ("MNQ", 2, 0.5), ("ES", 50, 12.5), ("MES", 5, 1.25)],
)
def test_multipliers_and_tick_values(symbol, mult, tick_value):
    inst = get_instrument(symbol)
    assert inst.multiplier == mult
    assert inst.tick_size == 0.25
    assert inst.tick_value == tick_value


def test_unknown_product_fails_loudly():
    with pytest.raises(UnknownProductError, match="XYZ"):
        get_instrument("XYZ")
