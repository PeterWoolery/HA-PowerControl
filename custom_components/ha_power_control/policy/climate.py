"""Pure-Python climate policy. No HA imports.

Spec: docs/superpowers/specs/2026-05-03-ha-power-control-design.md §6.2
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
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

    captured = persisted.get("captured_originals")

    # Falling edge of peak window: restore originals
    if persisted.get("peak_hold_active") and not inp.in_peak_window and captured:
        persisted["peak_hold_active"] = False
        persisted["precool_active"] = False
        persisted["precool_ran_this_cycle"] = False
        persisted["captured_originals"] = None
        return Action(
            kind=ActionKind.RESTORE,
            target_high_f=captured["target_high_f"],
            preset=captured["preset"],
            next_persisted=persisted,
            log_reason="peak_window_ended",
        )

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
            return Action(
                kind=ActionKind.RESTORE,
                target_high_f=captured["target_high_f"],
                preset=captured["preset"],
                next_persisted=persisted,
                log_reason="precool_aborted",
            )

    # Cold-start mid-peak: captured_originals present but precool never ran → abandon.
    if (
        inp.in_peak_window
        and persisted.get("captured_originals")
        and not persisted.get("precool_ran_this_cycle")
    ):
        originals = persisted["captured_originals"]
        persisted["peak_hold_active"] = False
        persisted["precool_active"] = False
        return Action(
            kind=ActionKind.RESTORE,
            target_high_f=originals["target_high_f"],
            preset=originals["preset"],
            next_persisted=persisted,
            log_reason="cold_start_abandon",
        )

    # Peak-hold steady-state: already in hold — T7 handles restore at peak end.
    if inp.in_peak_window and persisted.get("peak_hold_active"):
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
            target_high_f=inp.options["peak_max_temp_f"],
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
        new_high = inp.climate_target_high_f - inp.options["precool_offset_f"]
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
