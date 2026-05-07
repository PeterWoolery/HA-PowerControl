"""DataUpdateCoordinator — assembles PowerState from configured entities."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BATTERY_CHARGE_SWITCH,
    CONF_BATTERY_CHARGE_W,
    CONF_BATTERY_DISCHARGE_W,
    CONF_BATTERY_SOC,
    CONF_CLIMATE,
    CONF_INDOOR_TEMPS,
    CONF_NET_EXPORT_KWH,
    CONF_NET_IMPORT_KWH,
    CONF_NET_W,
    CONF_NET_W_SIGN,
    CONF_SOLAR_W,
    DEFAULT_UPDATE_INTERVAL_S,
    DEFAULTS,
    DOMAIN,
)
from .entity_map import EntityMap
from .models import (
    BatteryState,
    ClimateState,
    PowerState,
    compute_export_w,
    compute_mean_indoor_f,
)
from .policy.climate import ClimateInputs, decide
from .policy.climate_runner import ClimateRunner
from .store import HAPowerControlStore
from .tou import is_peak, seconds_until_peak_start

_LOGGER = logging.getLogger(__name__)


def _state_float(s: State | None) -> float | None:
    if s is None or s.state in ("unavailable", "unknown", None):
        return None
    try:
        return float(s.state)
    except (TypeError, ValueError):
        return None


def _normalize_kw_to_w(s: State | None) -> float | None:
    """Normalize a power sensor's value to W regardless of unit."""
    if s is None:
        return None
    raw = _state_float(s)
    if raw is None:
        return None
    unit = s.attributes.get("unit_of_measurement", "")
    if unit in ("kW", "kw"):
        return raw * 1000.0
    return raw


class HAPowerControlCoordinator(DataUpdateCoordinator[PowerState]):
    """30-second coordinator producing a PowerState snapshot."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        entity_map: EntityMap,
        store: HAPowerControlStore,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_UPDATE_INTERVAL_S),
        )
        self.entry = entry
        self.entity_map = entity_map
        self.store = store
        for eid in entity_map.indoor_temp_entities:
            entity_map.included_indoor_temps.setdefault(eid, True)
        # Sustained-export tracker for precool gate (spec §6.2 Phase 1)
        self._export_run_started: datetime | None = None
        self._runner: ClimateRunner | None = None

    def _ensure_runner(self) -> ClimateRunner:
        if self._runner is None:
            self._runner = ClimateRunner(
                hass=self.hass,
                climate_entity=self.entity_map.climate_entity,
                save_climate_state=self.store.set_climate_state,
                dry_run_getter=lambda: bool(
                    self.entry.options.get("dry_run", True)
                ),
            )
        return self._runner

    async def _async_update_data(self) -> PowerState:
        em = self.entity_map
        ts = dt_util.utcnow().astimezone(dt_util.DEFAULT_TIME_ZONE)

        net_w_raw = _normalize_kw_to_w(self.hass.states.get(em.net_w_entity))
        net_w = (net_w_raw or 0.0) * em.net_w_sign
        export_w = compute_export_w(net_w)

        solar_w: float | None = None
        if em.solar_w_entity:
            solar_w = _normalize_kw_to_w(self.hass.states.get(em.solar_w_entity))

        indoor_temps: dict[str, float | None] = {}
        for eid in em.indoor_temp_entities:
            if not em.included_indoor_temps.get(eid, True):
                continue
            indoor_temps[eid] = _state_float(self.hass.states.get(eid))
        mean_f = compute_mean_indoor_f(indoor_temps)

        cs = self.hass.states.get(em.climate_entity)
        if cs is not None:
            climate = ClimateState(
                current_f=cs.attributes.get("current_temperature"),
                target_low_f=cs.attributes.get("target_temp_low"),
                target_high_f=cs.attributes.get("target_temp_high"),
                preset=cs.attributes.get("preset_mode"),
                hvac_mode=cs.state,
                hvac_action=cs.attributes.get("hvac_action"),
            )
        else:
            climate = ClimateState(None, None, None, None, None, None)

        battery: BatteryState | None = None
        if em.battery_present():
            soc = _state_float(self.hass.states.get(em.battery_soc_entity))
            ac_in = (
                _normalize_kw_to_w(self.hass.states.get(em.battery_charge_w_entity))
                if em.battery_charge_w_entity
                else 0.0
            )
            ac_out = (
                _normalize_kw_to_w(self.hass.states.get(em.battery_discharge_w_entity))
                if em.battery_discharge_w_entity
                else 0.0
            )
            ac_in = ac_in or 0.0
            ac_out = ac_out or 0.0
            battery = BatteryState(
                soc_pct=soc if soc is not None else 0.0,
                ac_in_w=ac_in,
                ac_out_w=ac_out,
                charging=ac_in > 50.0,
                discharging=ac_out > 50.0,
                max_charge_w=1500.0,
                present=True,
            )

        # Spec §6.2: track sustained export ≥ charge_threshold_w
        threshold = float(
            self.entry.options.get("charge_threshold_w", DEFAULTS["charge_threshold_w"])
        )
        if export_w >= threshold:
            if self._export_run_started is None:
                self._export_run_started = ts
            export_run_seconds = (ts - self._export_run_started).total_seconds()
        else:
            self._export_run_started = None
            export_run_seconds = 0.0

        in_peak = is_peak(ts)
        state = PowerState(
            ts=ts,
            net_w=net_w,
            export_w=export_w,
            export_run_seconds=export_run_seconds,
            solar_w=solar_w,
            battery=battery,
            climate=climate,
            indoor_temps=indoor_temps,
            mean_indoor_f=mean_f,
            in_peak_window=in_peak,
            tou_period="peak" if in_peak else "off_peak",
            today_kwh_imported=0.0,
            today_kwh_exported=0.0,
            today_peak_savings_usd=0.0,
        )

        # Climate policy tick
        try:
            options = {**DEFAULTS, **dict(self.entry.options)}
            inputs = ClimateInputs(
                ts=ts,
                export_w=state.export_w,
                export_run_seconds=state.export_run_seconds,
                mean_indoor_f=state.mean_indoor_f,
                climate_current_f=state.climate.current_f,
                climate_target_high_f=state.climate.target_high_f,
                climate_target_low_f=state.climate.target_low_f,
                climate_preset=state.climate.preset,
                climate_hvac_mode=state.climate.hvac_mode,
                in_peak_window=state.in_peak_window,
                seconds_until_peak_start=seconds_until_peak_start(ts),
                persisted=self.store.get_climate_state(),
                options=options,
            )
            action = decide(inputs)
            await self._ensure_runner().apply(
                action, ts, current_target_low_f=state.climate.target_low_f,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("climate policy tick failed; coordinator continues")

        return state


def build_entity_map(data: dict[str, Any]) -> EntityMap:
    return EntityMap(
        net_w_entity=data[CONF_NET_W],
        net_import_kwh_entity=data[CONF_NET_IMPORT_KWH],
        net_export_kwh_entity=data[CONF_NET_EXPORT_KWH],
        climate_entity=data[CONF_CLIMATE],
        indoor_temp_entities=data[CONF_INDOOR_TEMPS],
        net_w_sign=data.get(CONF_NET_W_SIGN, 1),
        solar_w_entity=data.get(CONF_SOLAR_W),
        battery_soc_entity=data.get(CONF_BATTERY_SOC),
        battery_charge_w_entity=data.get(CONF_BATTERY_CHARGE_W),
        battery_discharge_w_entity=data.get(CONF_BATTERY_DISCHARGE_W),
        battery_charge_switch_entity=data.get(CONF_BATTERY_CHARGE_SWITCH),
    )
