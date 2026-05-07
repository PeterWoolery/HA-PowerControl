"""Unit tests for the climate-controller decide() function."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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


def test_precool_starts_when_all_gates_pass() -> None:
    inp = _inputs(
        export_w=300.0,
        export_run_seconds=700.0,  # > 10 min
        mean_indoor_f=78.0,  # warm enough
        seconds_until_peak_start=30 * 60,  # 30 min until peak (within precool_lead_min=60)
    )
    out = decide(inp)
    assert out.kind == ActionKind.PRECOOL_START
    assert out.target_high_f == 76.0 - 4.0  # captured.target_high - precool_offset
    assert out.next_persisted["precool_active"] is True
    assert out.next_persisted["precool_ran_this_cycle"] is True
    assert out.next_persisted["captured_originals"] == {
        "target_high_f": 76.0,
        "target_low_f": 68.0,
        "preset": "home",
        "captured_at": _now().isoformat(),
    }


def test_precool_skipped_when_export_run_too_short() -> None:
    inp = _inputs(
        export_w=300.0,
        export_run_seconds=300.0,  # only 5 min — fails ≥10 min gate
        mean_indoor_f=78.0,
        seconds_until_peak_start=30 * 60,
    )
    assert decide(inp).kind == ActionKind.NOOP


def test_precool_skipped_when_too_early_for_peak() -> None:
    inp = _inputs(
        export_w=300.0,
        export_run_seconds=700.0,
        mean_indoor_f=78.0,
        seconds_until_peak_start=4 * 60 * 60,  # 4h out — outside 60-min window
    )
    assert decide(inp).kind == ActionKind.NOOP


def test_precool_skipped_when_indoor_already_cool() -> None:
    inp = _inputs(
        export_w=300.0,
        export_run_seconds=700.0,
        mean_indoor_f=70.0,  # below peak_max_temp_f − precool_offset = 76
        seconds_until_peak_start=30 * 60,
    )
    assert decide(inp).kind == ActionKind.NOOP


def test_precool_skipped_during_sleep_window() -> None:
    sleep_ts = datetime(2026, 5, 6, 23, 0, 0, tzinfo=UTC)
    inp = _inputs(
        ts=sleep_ts,
        export_w=300.0,
        export_run_seconds=700.0,
        mean_indoor_f=78.0,
        seconds_until_peak_start=30 * 60,
    )
    assert decide(inp).kind == ActionKind.NOOP


def test_precool_skipped_when_dry_run_on() -> None:
    opts = _options_default()
    opts["dry_run"] = True
    inp = _inputs(
        export_w=300.0,
        export_run_seconds=700.0,
        mean_indoor_f=78.0,
        seconds_until_peak_start=30 * 60,
        options=opts,
    )
    # Dry-run is enforced by the runner, not the policy. Policy still emits the
    # action; runner is responsible for the gate. This test pins that contract.
    assert decide(inp).kind == ActionKind.PRECOOL_START


def test_peak_hold_starts_at_peak_when_precool_was_active() -> None:
    persisted = _persisted_empty()
    persisted["precool_active"] = True
    persisted["precool_ran_this_cycle"] = True
    persisted["captured_originals"] = {
        "target_high_f": 76.0,
        "target_low_f": 68.0,
        "preset": "home",
        "captured_at": _now().isoformat(),
    }
    inp = _inputs(
        in_peak_window=True,
        seconds_until_peak_start=0,
        climate_target_high_f=72.0,  # currently in precool
        persisted=persisted,
    )
    out = decide(inp)
    assert out.kind == ActionKind.PEAK_HOLD_START
    assert out.target_high_f == 80.0  # peak_max_temp_f
    assert out.next_persisted["precool_active"] is False
    assert out.next_persisted["peak_hold_active"] is True
    # captured_originals MUST be preserved across the transition
    assert out.next_persisted["captured_originals"] == persisted["captured_originals"]


def test_peak_hold_does_not_enter_without_precool_ran_this_cycle() -> None:
    """Cold-start mid-peak: persisted says peak_hold_active but no precool ran."""
    persisted = _persisted_empty()
    persisted["peak_hold_active"] = True
    persisted["precool_ran_this_cycle"] = False  # corrupt / cold start
    persisted["captured_originals"] = {
        "target_high_f": 76.0,
        "target_low_f": 68.0,
        "preset": "home",
        "captured_at": _now().isoformat(),
    }
    inp = _inputs(in_peak_window=True, seconds_until_peak_start=0, persisted=persisted)
    out = decide(inp)
    # Spec §6.2: abandon cycle, restore originals.
    assert out.kind == ActionKind.RESTORE
    assert out.next_persisted["peak_hold_active"] is False
    assert out.next_persisted["precool_ran_this_cycle"] is False


def test_restore_at_peak_window_falling_edge() -> None:
    persisted = _persisted_empty()
    persisted["peak_hold_active"] = True
    persisted["precool_ran_this_cycle"] = True
    persisted["captured_originals"] = {
        "target_high_f": 76.0,
        "target_low_f": 68.0,
        "preset": "home",
        "captured_at": _now().isoformat(),
    }
    # Peak just ended
    inp = _inputs(in_peak_window=False, persisted=persisted)
    out = decide(inp)
    assert out.kind == ActionKind.RESTORE
    assert out.target_high_f == 76.0
    assert out.preset == "home"
    assert out.next_persisted["peak_hold_active"] is False
    assert out.next_persisted["precool_active"] is False
    assert out.next_persisted["precool_ran_this_cycle"] is False
    assert out.next_persisted["captured_originals"] is None


def test_precool_aborts_when_export_collapses_before_peak() -> None:
    persisted = _persisted_empty()
    persisted["precool_active"] = True
    persisted["precool_ran_this_cycle"] = True
    persisted["captured_originals"] = {
        "target_high_f": 76.0,
        "target_low_f": 68.0,
        "preset": "home",
        "captured_at": _now().isoformat(),
    }
    inp = _inputs(
        export_w=0.0,  # collapsed
        export_run_seconds=0.0,
        in_peak_window=False,
        seconds_until_peak_start=20 * 60,
        persisted=persisted,
    )
    out = decide(inp)
    assert out.kind == ActionKind.RESTORE
    assert out.target_high_f == 76.0
    assert out.next_persisted["precool_active"] is False


def test_precool_aborts_when_sleep_window_starts() -> None:
    persisted = _persisted_empty()
    persisted["precool_active"] = True
    persisted["precool_ran_this_cycle"] = True
    persisted["captured_originals"] = {
        "target_high_f": 76.0,
        "target_low_f": 68.0,
        "preset": "home",
        "captured_at": _now().isoformat(),
    }
    sleep_ts = datetime(2026, 5, 6, 23, 0, 0, tzinfo=UTC)
    inp = _inputs(
        ts=sleep_ts,
        export_w=300.0,
        export_run_seconds=700.0,
        in_peak_window=False,
        persisted=persisted,
    )
    out = decide(inp)
    assert out.kind == ActionKind.RESTORE


def test_peak_hold_aborts_when_indoor_exceeds_ceiling() -> None:
    persisted = _persisted_empty()
    persisted["peak_hold_active"] = True
    persisted["precool_ran_this_cycle"] = True
    persisted["captured_originals"] = {
        "target_high_f": 76.0, "target_low_f": 68.0,
        "preset": "home", "captured_at": _now().isoformat(),
    }
    inp = _inputs(
        in_peak_window=True,
        mean_indoor_f=82.0,  # above peak_max_temp_f=80
        persisted=persisted,
    )
    out = decide(inp)
    assert out.kind == ActionKind.RESTORE
    assert out.target_high_f == 76.0
    assert out.next_persisted["peak_hold_active"] is False


def test_drift_detected_starts_cooldown() -> None:
    written_at = _now() - timedelta(seconds=120)  # outside grace
    persisted = _persisted_empty()
    persisted["precool_active"] = True
    persisted["precool_ran_this_cycle"] = True
    persisted["captured_originals"] = {
        "target_high_f": 76.0, "target_low_f": 68.0,
        "preset": "home", "captured_at": _now().isoformat(),
    }
    persisted["last_write_record"] = {
        "target_high": 72.0,  # we wrote 72
        "preset": "home",
        "written_at": written_at.isoformat(),
    }
    # User has bumped thermostat to 74 — drift > 0.5°F
    inp = _inputs(climate_target_high_f=74.0, persisted=persisted)
    out = decide(inp)
    assert out.kind == ActionKind.SET_COOLDOWN
    assert out.next_persisted["cooldown_until"] is not None
    # No write follows; precool stays active in persisted but writes suppressed.


def test_drift_within_grace_does_not_trigger() -> None:
    written_at = _now() - timedelta(seconds=30)  # inside drift_grace_s=60
    persisted = _persisted_empty()
    persisted["precool_active"] = True
    persisted["precool_ran_this_cycle"] = True
    persisted["captured_originals"] = {
        "target_high_f": 76.0, "target_low_f": 68.0,
        "preset": "home", "captured_at": _now().isoformat(),
    }
    persisted["last_write_record"] = {
        "target_high": 72.0,
        "preset": "home",
        "written_at": written_at.isoformat(),
    }
    # Thermostat hasn't reflected the write yet
    inp = _inputs(climate_target_high_f=76.0, persisted=persisted)
    out = decide(inp)
    assert out.kind != ActionKind.SET_COOLDOWN


def test_cooldown_suppresses_actions() -> None:
    cooldown_until = _now() + timedelta(minutes=10)
    persisted = _persisted_empty()
    persisted["cooldown_until"] = cooldown_until.isoformat()
    inp = _inputs(
        export_w=300.0,
        export_run_seconds=700.0,
        mean_indoor_f=78.0,
        seconds_until_peak_start=30 * 60,
        persisted=persisted,
    )
    assert decide(inp).kind == ActionKind.NOOP
