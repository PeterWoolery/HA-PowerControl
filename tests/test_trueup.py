"""NEM 2.0 true-up projector tests against MarchBill.pdf fixture."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.ha_power_control.rates_loader import load_rate_table
from custom_components.ha_power_control.trueup import (
    BillingPeriod,
    project_monthly_nem_charges,
    project_sjce_charges,
)

FIXTURE = Path(__file__).parent / "fixtures" / "march_bill_2026.json"


@pytest.fixture
def march_2026() -> dict:
    with FIXTURE.open() as fh:
        return json.load(fh)


@pytest.fixture
def rate_table():
    return load_rate_table()


def _period(data: dict) -> BillingPeriod:
    return BillingPeriod(
        billing_days=data["billing_days"],
        net_peak_kwh=data["net_peak_kwh"],
        net_off_peak_kwh=data["net_off_peak_kwh"],
        imports_kwh=data["imports_kwh"],
        exports_kwh=data["exports_kwh"],
    )


def test_pge_net_peak_charge(march_2026, rate_table) -> None:
    period = _period(march_2026)
    result = project_monthly_nem_charges(period, rate_table)
    assert result.pge_net_peak_charge == pytest.approx(
        march_2026["expected"]["pge_net_peak_charge"], abs=0.01
    )


def test_pge_net_off_peak_charge(march_2026, rate_table) -> None:
    period = _period(march_2026)
    result = project_monthly_nem_charges(period, rate_table)
    assert result.pge_net_off_peak_charge == pytest.approx(
        march_2026["expected"]["pge_net_off_peak_charge"], abs=0.01
    )


def test_monthly_nem_charges_within_one_dollar(march_2026, rate_table) -> None:
    period = _period(march_2026)
    result = project_monthly_nem_charges(period, rate_table)
    assert result.total == pytest.approx(
        march_2026["expected"]["monthly_nem_charges_total"], abs=1.0
    )


def test_sjce_peak_charge(march_2026, rate_table) -> None:
    period = _period(march_2026)
    sjce = project_sjce_charges(period, rate_table)
    assert sjce.peak_charge == pytest.approx(march_2026["expected"]["sjce_peak_charge"], abs=0.01)


def test_sjce_off_peak_charge(march_2026, rate_table) -> None:
    period = _period(march_2026)
    sjce = project_sjce_charges(period, rate_table)
    assert sjce.off_peak_charge == pytest.approx(
        march_2026["expected"]["sjce_off_peak_charge"], abs=0.01
    )


def test_cumulative_carry_forward(rate_table, march_2026) -> None:
    period = _period(march_2026)
    result = project_monthly_nem_charges(period, rate_table)
    cumulative_prior = 1488.89
    cumulative_after = cumulative_prior + result.total
    assert cumulative_after == pytest.approx(
        march_2026["ytd_cumulative_balance_through_period"], abs=5.0
    )
