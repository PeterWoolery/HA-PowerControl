"""Tests for data models."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from custom_components.ha_power_control.models import (
    BatteryState,
    ClimateState,
    PowerState,
    compute_export_w,
    compute_mean_indoor_f,
)

TZ = ZoneInfo("America/Los_Angeles")


def test_compute_export_w_when_importing_returns_zero() -> None:
    assert compute_export_w(net_w=500.0) == 0.0


def test_compute_export_w_when_exporting_returns_positive_magnitude() -> None:
    assert compute_export_w(net_w=-1500.0) == 1500.0


def test_compute_mean_indoor_f_with_all_valid() -> None:
    sensors = {"sensor.bedroom_temperature": 70.0, "sensor.elliott_temperature": 72.0}
    assert compute_mean_indoor_f(sensors) == 71.0


def test_compute_mean_indoor_f_with_some_none_filters() -> None:
    sensors = {"a": 70.0, "b": None, "c": 72.0}
    assert compute_mean_indoor_f(sensors) == 71.0


def test_compute_mean_indoor_f_with_all_none_returns_none() -> None:
    assert compute_mean_indoor_f({"a": None, "b": None}) is None


def test_compute_mean_indoor_f_empty_dict_returns_none() -> None:
    assert compute_mean_indoor_f({}) is None


def test_powerstate_construction_minimal() -> None:
    ps = PowerState(
        ts=datetime(2026, 5, 6, 18, 0, tzinfo=TZ),
        net_w=500.0,
        export_w=0.0,
        solar_w=None,
        battery=None,
        climate=ClimateState(
            current_f=70.0,
            target_low_f=68.0,
            target_high_f=76.0,
            preset="home",
            hvac_mode="heat_cool",
            hvac_action="idle",
        ),
        indoor_temps={"sensor.bedroom_temperature": 70.0},
        mean_indoor_f=70.0,
        in_peak_window=True,
        tou_period="peak",
        today_kwh_imported=5.0,
        today_kwh_exported=2.0,
        today_peak_savings_usd=0.0,
    )
    assert ps.in_peak_window is True
    assert ps.battery is None


def test_battery_state_construction() -> None:
    bs = BatteryState(
        soc_pct=50.0,
        ac_in_w=0.0,
        ac_out_w=200.0,
        charging=False,
        discharging=True,
        max_charge_w=1500.0,
        present=True,
    )
    assert bs.discharging is True
