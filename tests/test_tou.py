"""E-TOU-D peak-window tests."""
from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from custom_components.ha_power_control.tou import (
    is_peak,
    is_us_holiday,
    seconds_until_peak_start,
)

TZ = ZoneInfo("America/Los_Angeles")


@pytest.mark.parametrize(
    "ts, expected",
    [
        (datetime(2026, 5, 6, 16, 59, 0, tzinfo=TZ), False),
        (datetime(2026, 5, 6, 17, 0, 0, tzinfo=TZ), True),
        (datetime(2026, 5, 6, 19, 59, 59, tzinfo=TZ), True),
        (datetime(2026, 5, 6, 20, 0, 0, tzinfo=TZ), False),
        (datetime(2026, 5, 9, 18, 0, 0, tzinfo=TZ), False),
        (datetime(2026, 5, 10, 18, 0, 0, tzinfo=TZ), False),
        (datetime(2026, 5, 25, 18, 0, 0, tzinfo=TZ), False),  # Memorial Day
        (datetime(2026, 7, 3, 18, 0, 0, tzinfo=TZ), False),  # Independence Day observed
    ],
)
def test_is_peak(ts: datetime, expected: bool) -> None:
    assert is_peak(ts) == expected


def test_is_us_holiday_returns_true_on_christmas_2026() -> None:
    ts = datetime(2026, 12, 25, 12, 0, tzinfo=TZ)
    assert is_us_holiday(ts) is True


def test_is_us_holiday_false_on_random_tuesday() -> None:
    ts = datetime(2026, 5, 12, 12, 0, tzinfo=TZ)
    assert is_us_holiday(ts) is False


def test_seconds_until_peak_start_pre_peak_same_day() -> None:
    ts = datetime(2026, 5, 6, 16, 30, 0, tzinfo=TZ)
    assert seconds_until_peak_start(ts) == 1800


def test_seconds_until_peak_start_during_peak_returns_zero() -> None:
    ts = datetime(2026, 5, 6, 18, 0, 0, tzinfo=TZ)
    assert seconds_until_peak_start(ts) == 0


def test_seconds_until_peak_start_post_peak_jumps_to_next_weekday() -> None:
    ts = datetime(2026, 5, 6, 20, 30, 0, tzinfo=TZ)
    expected = 20 * 3600 + 30 * 60
    assert seconds_until_peak_start(ts) == expected


def test_seconds_until_peak_start_friday_evening_jumps_to_monday() -> None:
    ts = datetime(2026, 5, 8, 21, 0, 0, tzinfo=TZ)
    assert seconds_until_peak_start(ts) == 68 * 3600


def test_seconds_until_peak_start_skips_holidays() -> None:
    ts = datetime(2026, 5, 24, 12, 0, 0, tzinfo=TZ)
    assert seconds_until_peak_start(ts) == 53 * 3600
