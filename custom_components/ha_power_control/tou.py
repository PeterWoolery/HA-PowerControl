"""E-TOU-D peak-window calculator (PG&E Schedule E-TOU-D)."""

from __future__ import annotations

from datetime import datetime, timedelta

import holidays

from .const import PEAK_DAYS, PEAK_HOUR_END, PEAK_HOUR_START

_HOLIDAY_CACHE: dict[int, holidays.HolidayBase] = {}


def _holidays_for(year: int) -> holidays.HolidayBase:
    if year not in _HOLIDAY_CACHE:
        _HOLIDAY_CACHE[year] = holidays.UnitedStates(years=year, observed=True)
    return _HOLIDAY_CACHE[year]


def is_us_holiday(ts: datetime) -> bool:
    """True iff ts.date() is a US federal holiday (observed)."""
    return ts.date() in _holidays_for(ts.year)


def is_peak(ts: datetime) -> bool:
    """True iff ts is in the E-TOU-D peak window (5pm-8pm M-F, holidays excluded)."""
    if ts.weekday() not in PEAK_DAYS:
        return False
    if is_us_holiday(ts):
        return False
    return PEAK_HOUR_START <= ts.hour < PEAK_HOUR_END


def _next_peak_start(ts: datetime) -> datetime:
    """First instant ≥ ts at which a peak window begins."""
    candidate = ts.replace(hour=PEAK_HOUR_START, minute=0, second=0, microsecond=0)
    if candidate <= ts:
        candidate = candidate + timedelta(days=1)
    while candidate.weekday() not in PEAK_DAYS or is_us_holiday(candidate):
        candidate = candidate + timedelta(days=1)
    return candidate


def seconds_until_peak_start(ts: datetime) -> int:
    """Whole seconds from ts until the next peak window begins. 0 if currently in peak."""
    if is_peak(ts):
        return 0
    delta = _next_peak_start(ts) - ts
    return int(delta.total_seconds())
