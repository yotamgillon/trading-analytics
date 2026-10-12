from typing import ClassVar, Protocol

import pandas as pd

from trading_analytics.quality.findings import Finding


class Adapter(Protocol):
    """One parser per platform export format."""

    name: ClassVar[str]
    # Header names that must ALL be present to claim a file (after whitespace stripping).
    signature: ClassVar[frozenset[str]]
    # Raw columns that must be non-blank on every row, and the column that uniquely IDs a fill.
    required_columns: ClassVar[tuple[str, ...]]
    id_column: ClassVar[str]

    def parse(self, raw: pd.DataFrame) -> pd.DataFrame:
        """Map a raw export (all columns as strings) to canonical fills."""
        ...

    def raw_checks(self, raw: pd.DataFrame) -> list[Finding]:
        """Platform-specific consistency checks on the raw export (warnings only)."""
        ...
