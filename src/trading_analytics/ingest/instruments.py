"""Contract specifications as a config table, not hardcoded constants.

Adding a product (e.g. YM) is one row here. Unknown products fail loudly: a silent default
multiplier would corrupt every P&L number downstream.
"""

from dataclasses import dataclass


class UnknownProductError(ValueError):
    pass


@dataclass(frozen=True)
class Instrument:
    symbol: str
    multiplier: float  # dollars per index point
    tick_size: float  # points

    @property
    def tick_value(self) -> float:
        return self.multiplier * self.tick_size


INSTRUMENTS: dict[str, Instrument] = {
    i.symbol: i
    for i in (
        Instrument("NQ", 20.0, 0.25),
        Instrument("MNQ", 2.0, 0.25),
        Instrument("ES", 50.0, 0.25),
        Instrument("MES", 5.0, 0.25),
    )
}


def get_instrument(symbol: str) -> Instrument:
    try:
        return INSTRUMENTS[symbol]
    except KeyError:
        raise UnknownProductError(
            f"Unknown product {symbol!r}; add it to INSTRUMENTS. Known: {sorted(INSTRUMENTS)}"
        ) from None
