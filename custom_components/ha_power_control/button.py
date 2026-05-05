"""Button platform: snapshot_state."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HAPowerControlCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coord: HAPowerControlCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SnapshotStateButton(coord, hass)])


class SnapshotStateButton(CoordinatorEntity[HAPowerControlCoordinator], ButtonEntity):
    _attr_has_entity_name = True

    def __init__(self, coord: HAPowerControlCoordinator, hass: HomeAssistant) -> None:
        super().__init__(coord)
        self._hass = hass
        self._attr_unique_id = f"{coord.entry.entry_id}_snapshot_state"
        self._attr_name = "Snapshot State"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coord.entry.entry_id)},
            name="HA Power Control",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_press(self) -> None:
        d = self.coordinator.data
        if d is None:
            return
        out_dir = Path(self._hass.config.path("ha_power_control", "snapshots"))
        ts = datetime.now().strftime("%Y%m%dT%H%M%S")
        payload = {
            "ts": d.ts.isoformat(),
            "net_w": d.net_w,
            "export_w": d.export_w,
            "solar_w": d.solar_w,
            "mean_indoor_f": d.mean_indoor_f,
            "in_peak_window": d.in_peak_window,
            "tou_period": d.tou_period,
            "today_kwh_imported": d.today_kwh_imported,
            "today_kwh_exported": d.today_kwh_exported,
            "today_peak_savings_usd": d.today_peak_savings_usd,
            "battery": None
            if d.battery is None
            else {
                "soc_pct": d.battery.soc_pct,
                "ac_in_w": d.battery.ac_in_w,
                "ac_out_w": d.battery.ac_out_w,
                "charging": d.battery.charging,
                "discharging": d.battery.discharging,
            },
        }
        text = json.dumps(payload, indent=2)

        def _write() -> None:
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / f"snapshot_{ts}.json").write_text(text)

        await asyncio.get_event_loop().run_in_executor(None, _write)
