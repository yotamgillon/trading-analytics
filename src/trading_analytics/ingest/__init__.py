from pathlib import Path

import pandas as pd

from trading_analytics.ingest.detect import detect_adapter


def load_fills(path: str | Path) -> pd.DataFrame:
    """Read an export, auto-detect its platform format, return canonical fills."""
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    adapter = detect_adapter(raw.columns)
    return adapter().parse(raw)
