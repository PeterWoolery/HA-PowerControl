"""Tests for rate-table loading."""
from __future__ import annotations
from datetime import date

import pytest

from custom_components.ha_power_control.rates_loader import RateTable, load_rate_table


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
