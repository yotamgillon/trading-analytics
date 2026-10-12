"""Individual quality checks. Policy: quarantine and report, never guess a value."""

import pandas as pd

from trading_analytics.ingest.instruments import INSTRUMENTS
from trading_analytics.market.sessions import is_trading_day
from trading_analytics.quality.findings import Finding, QualityError, examples_of
from trading_analytics.quality.timezone import session_trade_date

MAX_PLAUSIBLE_QTY = 100  # contracts in one fill; above this is almost surely a typo
MAX_INTRADAY_DEVIATION = 0.08  # a fill > 8% from its contract-day median is a bad print/typo


def clean_raw(raw: pd.DataFrame, adapter) -> tuple[pd.DataFrame, pd.DataFrame, list[Finding]]:
    """Raw-string level: exact duplicates dropped, conflicting ids rejected, blanks quarantined."""
    raw = raw.rename(columns=str.strip)
    idc, findings = adapter.id_column, []

    exact = raw.duplicated(keep="first")
    if exact.any():
        findings.append(
            Finding(
                "duplicate_rows",
                "fixed",
                int(exact.sum()),
                "exact duplicate rows dropped (overlapping exports)",
                examples_of(raw.loc[exact, idc]),
            )
        )
        raw = raw[~exact]

    conflict = raw[idc].duplicated(keep=False)
    if conflict.any():
        raise QualityError(
            f"{int(conflict.sum())} rows share an id but differ in content "
            f"(ids: {', '.join(examples_of(raw.loc[conflict, idc]))}); fix the export by hand"
        )

    blank = raw[list(adapter.required_columns)].apply(lambda s: s.str.strip() == "").any(axis=1)
    quarantined = raw[blank].copy()
    if blank.any():
        quarantined["reason"] = "missing_value"
        findings.append(
            Finding(
                "missing_values",
                "fixed",
                int(blank.sum()),
                "rows with a blank required field were excluded (never imputed)",
                examples_of(raw.loc[blank, idc]),
            )
        )
    return raw[~blank].reset_index(drop=True), quarantined, findings


def quarantine_bad_prices(
    fills: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, list[Finding]]:
    findings = []
    tick = fills["symbol"].map(lambda s: INSTRUMENTS[s].tick_size)
    ratio = fills["price"] / tick
    off_tick = (ratio - ratio.round()).abs() > 1e-6
    if off_tick.any():
        findings.append(
            Finding(
                "off_tick_price",
                "fixed",
                int(off_tick.sum()),
                "price is not a multiple of the tick size, so it cannot be an exchange fill; "
                "excluded",
                examples_of(fills.loc[off_tick, "fill_id"]),
            )
        )

    grp = fills.groupby(["contract", "trade_date"])["price"]
    median = grp.transform("median")
    size = grp.transform("size")
    outlier = (
        (size >= 3) & ((fills["price"] / median - 1).abs() > MAX_INTRADAY_DEVIATION) & ~off_tick
    )
    if outlier.any():
        findings.append(
            Finding(
                "price_outlier",
                "fixed",
                int(outlier.sum()),
                f"price more than {MAX_INTRADAY_DEVIATION:.0%} from the contract-day median "
                "(fat-finger or typo); excluded",
                examples_of(fills.loc[outlier, "fill_id"]),
            )
        )
    bad = off_tick | outlier
    return fills[~bad].reset_index(drop=True), fills[bad], findings


def warn_checks(fills: pd.DataFrame) -> list[Finding]:
    out: list[Finding] = []

    big = fills["qty"] > MAX_PLAUSIBLE_QTY
    out.append(
        Finding(
            "large_quantity",
            "warning",
            int(big.sum()),
            f"fill quantity above {MAX_PLAUSIBLE_QTY} contracts (kept)",
            examples_of(fills.loc[big, "fill_id"]),
        )
    )

    derived = session_trade_date(fills["fill_time"])
    mismatch = derived != fills["trade_date"]
    out.append(
        Finding(
            "trade_date_mismatch",
            "warning",
            int(mismatch.sum()),
            "platform trade_date differs from the CME session date derived from UTC "
            "(session rolls at 18:00 ET); check timezone handling (kept)",
            examples_of(fills.loc[mismatch, "fill_id"]),
        )
    )

    closed = ~fills["trade_date"].map(is_trading_day)
    out.append(
        Finding(
            "non_trading_day",
            "warning",
            int(closed.sum()),
            "trade_date falls on a weekend or known exchange holiday (kept)",
            examples_of(fills.loc[closed, "fill_id"]),
        )
    )

    rate = (fills["commission"] / fills["qty"]).round(4)
    zero = rate == 0
    out.append(
        Finding(
            "zero_commission",
            "warning",
            int(zero.sum()),
            "fills with zero commission (kept; fees % will be understated)",
            examples_of(fills.loc[zero, "fill_id"]),
        )
    )
    nonzero = fills[~zero].assign(rate=rate[~zero])
    multi = nonzero.groupby("symbol")["rate"].nunique()
    for sym in multi[multi > 1].index:
        rates = sorted(float(r) for r in nonzero.loc[nonzero["symbol"] == sym, "rate"].unique())
        out.append(
            Finding(
                "commission_rate_varies",
                "warning",
                int(multi[sym]),
                f"{sym} commission per contract takes several values {rates} (kept)",
            )
        )

    order_parts = fills.groupby("order_id")[["side", "contract", "account"]].nunique()
    bad_orders = order_parts[(order_parts > 1).any(axis=1)].index
    out.append(
        Finding(
            "inconsistent_order",
            "warning",
            len(bad_orders),
            "fills of one order disagree on side/contract/account (kept)",
            examples_of(bad_orders),
        )
    )
    return [f for f in out if f.count > 0]


def desync_warning(excluded_contracts: set[str]) -> Finding | None:
    """Excluding a fill leaves the position out of step, so later trades on that contract drift."""
    if not excluded_contracts:
        return None
    return Finding(
        "excluded_fills_break_pairing",
        "warning",
        len(excluded_contracts),
        "fills were excluded on contract(s) "
        + ", ".join(sorted(excluded_contracts))
        + "; position tracking is out of step from the first exclusion, so trades on these "
        "contracts after that point are unreliable until the export is corrected",
    )
