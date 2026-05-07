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
