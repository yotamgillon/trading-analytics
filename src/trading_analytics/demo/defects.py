"""Deliberately corrupt a clean raw export so the quality checks have something to find.

Used by the tests and by `make quality-demo` (which writes the README's sample report).
Each defect maps to one check; counts are returned so tests can assert on them exactly.
"""

import numpy as np
import pandas as pd


def inject_defects(raw: pd.DataFrame, seed: int = 7) -> tuple[pd.DataFrame, dict[str, int]]:
    rng = np.random.default_rng(seed)
    df = raw.copy()
    rows = rng.permutation(len(df) - 1)[:9]  # never touch the last row

    def set_price(i, price):
        df.iloc[i, df.columns.get_loc("_price")] = str(price)
        df.iloc[i, df.columns.get_loc("Price")] = f"{price:.2f}"

    df.iloc[rows[0], df.columns.get_loc("_price")] = ""  # missing value
    set_price(rows[1], float(df.iloc[rows[1]]["_price"]) + 0.1)  # off-tick
    set_price(rows[2], float(df.iloc[rows[2]]["_price"]) * 10)  # fat finger
    df.iloc[rows[3], df.columns.get_loc("Timestamp")] = "01/01/2000 00:00:00"  # display clock off
    df.iloc[rows[4], df.columns.get_loc("_qty")] = "500"  # absurd size
    df.iloc[rows[4], df.columns.get_loc("Quantity")] = "500"
    df.iloc[rows[5], df.columns.get_loc("commission")] = "0.0"  # free commission

    inactive = df.iloc[[rows[6]]].copy()  # an extra inactive fill (a busted/ghost print)
    inactive["_id"] = inactive["Fill ID"] = "999999999001"
    inactive["_active"] = "false"
    dupes = df.iloc[rows[7:9]].copy()  # re-export overlap
    return pd.concat([df, inactive, dupes], ignore_index=True), {
        "missing_values": 1,
        "off_tick_price": 1,
        "price_outlier": 1,
        "display_time_mismatch": 1,
        "large_quantity": 1,
        "zero_commission": 1,
        "inactive_fills": 1,
        "duplicate_rows": 2,
    }
