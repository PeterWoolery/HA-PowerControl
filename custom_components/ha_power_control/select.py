"""Select platform: operating_mode."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULTS, DOMAIN, MODES
from .coordinator import HAPowerControlCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coord: HAPowerControlCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([OperatingModeSelect(coord)])


class OperatingModeSelect(CoordinatorEntity[HAPowerControlCoordinator], SelectEntity):
    _attr_has_entity_name = True
    _attr_options = MODES

    def __init__(self, coord: HAPowerControlCoordinator) -> None:
        super().__init__(coord)
        self._attr_unique_id = f"{coord.entry.entry_id}_operating_mode"
        self._attr_name = "Operating Mode"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coord.entry.entry_id)},
            name="HA Power Control",
            entry_type=DeviceEntryType.SERVICE,
        )
        self._current: str = coord.entry.options.get("operating_mode", DEFAULTS["operating_mode"])

    @property
    def current_option(self) -> str:
        return self._current

    async def async_select_option(self, option: str) -> None:
        self._current = option
        new_options = {**self.coordinator.entry.options, "operating_mode": option}
        self.hass.config_entries.async_update_entry(self.coordinator.entry, options=new_options)
        self.async_write_ha_state()
