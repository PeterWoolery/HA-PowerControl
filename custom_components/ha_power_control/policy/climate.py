"""Pure-Python climate policy. No HA imports.

Spec: docs/superpowers/specs/2026-05-03-ha-power-control-design.md §6.2
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any


class ActionKind(StrEnum):
    NOOP = "noop"
    PRECOOL_START = "precool_start"
    PEAK_HOLD_START = "peak_hold_start"
    RESTORE = "restore"
    SET_COOLDOWN = "set_cooldown"


@dataclass(frozen=True)
class Action:
    kind: ActionKind
    target_high_f: float | None = None
    preset: str | None = None
    next_persisted: dict[str, Any] = field(default_factory=dict)
    log_reason: str = ""


@dataclass(frozen=True)
class ClimateInputs:
    ts: datetime
    export_w: float
    export_run_seconds: float
    mean_indoor_f: float | None
    climate_current_f: float | None
    climate_target_high_f: float | None
    climate_target_low_f: float | None
    climate_preset: str | None
    climate_hvac_mode: str | None
    in_peak_window: bool
    seconds_until_peak_start: int
    persisted: dict[str, Any]
    options: dict[str, Any]


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _make_restore_action(
    persisted: dict[str, Any],
    captured: dict[str, Any],
    options: dict[str, Any],
    log_reason: str,
) -> Action:
    return Action(
        kind=ActionKind.RESTORE,
        target_high_f=_clamp(
            captured["target_high_f"], options["min_cool_f"], options["max_cool_f"]
        ),
        preset=captured.get("preset"),
        next_persisted=persisted,
        log_reason=log_reason,
    )


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _drift_detected(inp: ClimateInputs) -> bool:
    rec = inp.persisted.get("last_write_record")
    if not rec:
        return False
    written_at = _parse_iso(rec.get("written_at"))
    if written_at is None:
        return False
    grace_s = inp.options["drift_grace_s"]
    if (inp.ts - written_at).total_seconds() < grace_s:
        return False
    tol = inp.options["drift_tolerance_f"]
    high_drift = (
        inp.climate_target_high_f is not None
        and abs(inp.climate_target_high_f - rec["target_high"]) > tol
    )
    rec_preset = rec.get("preset")
    preset_drift = rec_preset is not None and inp.climate_preset != rec_preset
    return high_drift or preset_drift


def _is_healthy(inp: ClimateInputs) -> bool:
    return (
        inp.climate_hvac_mode == "heat_cool"
        and inp.climate_target_high_f is not None
        and inp.climate_target_low_f is not None
    )


def _in_sleep_window(ts: datetime, start_h: int, end_h: int) -> bool:
    h = ts.hour
    if start_h <= end_h:
        return start_h <= h < end_h
    return h >= start_h or h < end_h


def _precool_gates_pass(inp: ClimateInputs) -> bool:
    o = inp.options
    p = inp.persisted

    if p.get("precool_active") or p.get("peak_hold_active"):
        return False  # already in cycle
    if inp.in_peak_window:
        return False  # too late
    if inp.export_w < o["charge_threshold_w"]:
        return False
    if inp.export_run_seconds < 600:  # 10 min
        return False
    lead_s = o["precool_lead_min"] * 60
    if not (0 < inp.seconds_until_peak_start <= lead_s):
        return False
    if inp.mean_indoor_f is None:
        return False
    if inp.mean_indoor_f <= o["peak_max_temp_f"] - o["precool_offset_f"]:
        return False
    return not _in_sleep_window(inp.ts, o["sleep_start_h"], o["sleep_end_h"])


def decide(inp: ClimateInputs) -> Action:
    """Return the Action the runner should execute this tick."""
    persisted = dict(inp.persisted)

    if not inp.options.get("climate_override_enabled", False):
        return Action(
            kind=ActionKind.NOOP, next_persisted=persisted, log_reason="override_disabled"
        )

    if not _is_healthy(inp):
        return Action(
            kind=ActionKind.NOOP, next_persisted=persisted, log_reason="climate_unhealthy"
        )

    # Cooldown gate
    cooldown_until = _parse_iso(persisted.get("cooldown_until"))
    if cooldown_until and inp.ts < cooldown_until:
        return Action(kind=ActionKind.NOOP, next_persisted=persisted, log_reason="in_cooldown")
    if cooldown_until and inp.ts >= cooldown_until:
        persisted["cooldown_until"] = None  # cooldown elapsed; clear

    # External override detection — only meaningful when we have an active
    # cycle or have written recently. Avoids spurious cooldowns at idle.
    has_active_cycle_or_write = (
        persisted.get("precool_active")
        or persisted.get("peak_hold_active")
        or persisted.get("last_write_record") is not None
    )
    if has_active_cycle_or_write and _drift_detected(inp):
        cd_min = inp.options["cooldown_min"]
        persisted["cooldown_until"] = (inp.ts + timedelta(minutes=cd_min)).isoformat()
        return Action(
            kind=ActionKind.SET_COOLDOWN,
            next_persisted=persisted,
            log_reason="drift_detected",
        )

    captured = persisted.get("captured_originals")

    # Falling edge of peak window: restore originals
    if persisted.get("peak_hold_active") and not inp.in_peak_window and captured:
        persisted["peak_hold_active"] = False
        persisted["precool_active"] = False
        persisted["precool_ran_this_cycle"] = False
        persisted["captured_originals"] = None
        return _make_restore_action(persisted, captured, inp.options, "peak_window_ended")

    # Precool active but conditions ceased before peak start
    if persisted.get("precool_active") and not inp.in_peak_window and captured:
        export_ok = (
            inp.export_run_seconds >= 600 and inp.export_w >= inp.options["charge_threshold_w"]
        )
        sleeping = _in_sleep_window(
            inp.ts, inp.options["sleep_start_h"], inp.options["sleep_end_h"]
        )
        if (not export_ok) or sleeping:
            persisted["precool_active"] = False
            persisted["precool_ran_this_cycle"] = False
            persisted["captured_originals"] = None
            return _make_restore_action(persisted, captured, inp.options, "precool_aborted")

    # Cold-start mid-peak: captured_originals present but precool never ran → abandon.
    if (
        inp.in_peak_window
        and persisted.get("captured_originals")
        and not persisted.get("precool_ran_this_cycle")
    ):
        originals = persisted["captured_originals"]
        persisted["peak_hold_active"] = False
        persisted["precool_active"] = False
        return _make_restore_action(persisted, originals, inp.options, "cold_start_abandon")

    # Peak-hold steady-state: already in hold — T7 handles restore at peak end.
    if inp.in_peak_window and persisted.get("peak_hold_active"):
        if (
            inp.mean_indoor_f is not None
            and inp.mean_indoor_f > inp.options["peak_max_temp_f"]
            and captured is not None
        ):
            persisted["peak_hold_active"] = False
            persisted["precool_active"] = False
            persisted["precool_ran_this_cycle"] = False
            persisted["captured_originals"] = None
            return _make_restore_action(
                persisted, captured, inp.options, "hard_exit_temp_above_ceiling"
            )
        return Action(
            kind=ActionKind.NOOP,
            next_persisted=persisted,
            log_reason="peak_hold_steady",
        )

    # Phase 1 → 2 transition: precool was active, peak window just opened.
    if inp.in_peak_window and persisted.get("precool_active"):
        if not persisted.get("precool_ran_this_cycle"):
            # Defensive: precool_active without precool_ran should not happen.
            persisted["precool_active"] = False
            persisted["peak_hold_active"] = False
            return Action(
                kind=ActionKind.RESTORE,
                next_persisted=persisted,
                log_reason="corrupt_state_abandon",
            )
        persisted["precool_active"] = False
        persisted["peak_hold_active"] = True
        return Action(
            kind=ActionKind.PEAK_HOLD_START,
            target_high_f=_clamp(
                inp.options["peak_max_temp_f"],
                inp.options["min_cool_f"],
                inp.options["max_cool_f"],
            ),
            next_persisted=persisted,
            log_reason="peak_hold_transition",
        )

    if _precool_gates_pass(inp):
        captured = {
            "target_high_f": inp.climate_target_high_f,
            "target_low_f": inp.climate_target_low_f,
            "preset": inp.climate_preset,
            "captured_at": inp.ts.isoformat(),
        }
        new_high = _clamp(
            inp.climate_target_high_f - inp.options["precool_offset_f"],
            inp.options["min_cool_f"],
            inp.options["max_cool_f"],
        )
        persisted["captured_originals"] = captured
        persisted["precool_active"] = True
        persisted["precool_ran_this_cycle"] = True
        return Action(
            kind=ActionKind.PRECOOL_START,
            target_high_f=new_high,
            next_persisted=persisted,
            log_reason="precool_gates_passed",
        )

    return Action(kind=ActionKind.NOOP, next_persisted=persisted, log_reason="idle")
