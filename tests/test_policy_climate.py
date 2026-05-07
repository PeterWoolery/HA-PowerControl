"""Unit tests for the climate-controller decide() function."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest  # noqa: F401

from custom_components.ha_power_control.policy.climate import (
    Action,  # noqa: F401 — used in T5+
    ActionKind,
    ClimateInputs,
    decide,
)


def _now() -> datetime:
    return datetime(2026, 5, 6, 14, 0, 0, tzinfo=UTC)


def _persisted_empty() -> dict[str, Any]:
    return {
        "captured_originals": None,
        "precool_active": False,
        "peak_hold_active": False,
        "precool_ran_this_cycle": False,
        "last_write_record": None,
        "cooldown_until": None,
    }


def _options_default() -> dict[str, Any]:
    return {
        "dry_run": False,
        "climate_override_enabled": True,
        "precool_offset_f": 4.0,
        "peak_max_temp_f": 80.0,
        "min_cool_f": 65.0,
        "max_cool_f": 82.0,
        "charge_threshold_w": 200.0,
        "drift_tolerance_f": 0.5,
        "drift_grace_s": 60,
        "cooldown_min": 30,
        "sleep_start_h": 22,
        "sleep_end_h": 6,
        "precool_lead_min": 60,
    }


def _inputs(**overrides) -> ClimateInputs:
    base: dict[str, Any] = {
        "ts": _now(),
        "export_w": 0.0,
        "export_run_seconds": 0.0,
        "mean_indoor_f": 72.0,
        "climate_current_f": 72.0,
        "climate_target_high_f": 76.0,
        "climate_target_low_f": 68.0,
        "climate_preset": "home",
        "climate_hvac_mode": "heat_cool",
        "in_peak_window": False,
        "seconds_until_peak_start": 86400,
        "persisted": _persisted_empty(),
        "options": _options_default(),
    }
    base.update(overrides)
    return ClimateInputs(**base)


def test_decide_idle_returns_noop_when_nothing_to_do() -> None:
    out = decide(_inputs())
    assert out.kind == ActionKind.NOOP
    assert out.next_persisted == _persisted_empty()


def test_decide_noop_when_climate_override_disabled() -> None:
    opts = _options_default()
    opts["climate_override_enabled"] = False
    out = decide(_inputs(options=opts))
    assert out.kind == ActionKind.NOOP


def test_decide_noop_when_climate_unhealthy() -> None:
    out = decide(_inputs(climate_hvac_mode="cool"))  # not heat_cool
    assert out.kind == ActionKind.NOOP
