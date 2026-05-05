"""Tests for rate-table loading."""

from __future__ import annotations

from datetime import date

import pytest

from custom_components.ha_power_control.rates_loader import load_rate_table


def test_load_default_rate_table() -> None:
    rt = load_rate_table()
    assert rt.schedule == "ETOUD-XB"
    assert rt.effective_from == date(2026, 3, 1)
    assert rt.pge_delivery_peak_per_kwh == pytest.approx(0.38747)
    assert rt.sjce_off_peak_per_kwh == pytest.approx(0.07921)


def test_combined_peak_rate() -> None:
    rt = load_rate_table()
    assert rt.combined_peak_per_kwh == pytest.approx(0.38747 + 0.11324)


def test_combined_off_peak_rate() -> None:
    rt = load_rate_table()
    assert rt.combined_off_peak_per_kwh == pytest.approx(0.34886 + 0.07921)


def test_load_rate_table_with_future_as_of_returns_latest() -> None:
    """When as_of is far in the future, the most-recent table is returned."""
    rt = load_rate_table(as_of=date(2099, 1, 1))
    assert rt.schedule == "ETOUD-XB"


def test_load_rate_table_with_past_as_of_falls_back_to_earliest() -> None:
    """When as_of predates all effective dates, fallback returns the earliest available."""
    rt = load_rate_table(as_of=date(2000, 1, 1))
    # We only have one rate table at 2026-03-01; that's both earliest and only candidate.
    assert rt.effective_from == date(2026, 3, 1)
