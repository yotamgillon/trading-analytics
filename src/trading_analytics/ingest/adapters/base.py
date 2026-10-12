from typing import ClassVar, Protocol

import pandas as pd


class Adapter(Protocol):
    """One parser per platform export format."""

    name: ClassVar[str]
    # Header names that must ALL be present to claim a file (after whitespace stripping).
    signature: ClassVar[frozenset[str]]

    def parse(self, raw: pd.DataFrame) -> pd.DataFrame:
        """Map a raw export (all columns as strings) to canonical fills."""
        ...
