"""Pure data models — no HA imports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass(frozen=True)
class BatteryState:
    soc_pct: float
    ac_in_w: float
    ac_out_w: float
    charging: bool
    discharging: bool
    max_charge_w: float
    present: bool


@dataclass(frozen=True)
class ClimateState:
    current_f: float | None
    target_low_f: float | None
    target_high_f: float | None
    preset: str | None
    hvac_mode: str | None
    hvac_action: str | None


@dataclass(frozen=True)
class PowerState:
    ts: datetime
    net_w: float
    export_w: float
    export_run_seconds: float  # seconds export has been ≥ charge_threshold_w
    solar_w: float | None
    battery: BatteryState | None
    climate: ClimateState
    indoor_temps: dict[str, float | None]
    mean_indoor_f: float | None
    in_peak_window: bool
    tou_period: Literal["peak", "off_peak"]
    today_kwh_imported: float
    today_kwh_exported: float
    today_peak_savings_usd: float


def compute_export_w(net_w: float) -> float:
    """Export magnitude (positive when net_w is negative = exporting)."""
    return max(0.0, -net_w)


def compute_mean_indoor_f(sensors: dict[str, float | None]) -> float | None:
    """Mean of valid (non-None) indoor temp readings; None if no valid readings."""
    valid = [v for v in sensors.values() if v is not None]
    if not valid:
        return None
    return sum(valid) / len(valid)
