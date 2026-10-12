"""Trading-day calendar for CME equity-index futures (maintained by hand, 2026).

Used to decide which days SHOULD have bars, so a missing day is flagged instead of silently
ignored. The regular-trading-hours (RTH) window is 09:30-16:00 ET; coverage is measured there.
Early closes / holidays are approximate: a flagged day is a prompt to look, not proof of a gap.
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
RTH_OPEN, RTH_CLOSE = time(9, 30), time(16, 0)

HOLIDAYS = {
    date(2026, 1, 1),
    date(2026, 1, 19),
    date(2026, 2, 16),
    date(2026, 4, 3),
    date(2026, 5, 25),
    date(2026, 6, 19),
    date(2026, 7, 3),
    date(2026, 9, 7),
    date(2026, 11, 26),
    date(2026, 12, 25),
    date(2027, 1, 1),
}
EARLY_CLOSE = {date(2026, 11, 27): time(13, 0), date(2026, 12, 24): time(13, 15)}


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in HOLIDAYS


def expected_trading_days(start: date, end: date) -> list[date]:
    """Trading days in [start, end] inclusive."""
    days = (start + timedelta(n) for n in range((end - start).days + 1))
    return [d for d in days if is_trading_day(d)]


def rth_close(d: date) -> time:
    return EARLY_CLOSE.get(d, RTH_CLOSE)


def rth_window_utc(d: date) -> tuple[datetime, datetime]:
    start = datetime.combine(d, RTH_OPEN, tzinfo=ET)
    end = datetime.combine(d, rth_close(d), tzinfo=ET)
    return start.astimezone(ZoneInfo("UTC")), end.astimezone(ZoneInfo("UTC"))


def expected_rth_bars(d: date, interval_minutes: int) -> int:
    start, end = rth_window_utc(d)
    return int((end - start).total_seconds() // 60 // interval_minutes)
