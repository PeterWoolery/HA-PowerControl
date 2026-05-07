"""Number platform: P1 tuneables (trueup_month, min/max_cool, peak_max_temp_f)."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULTS, DOMAIN
from .coordinator import HAPowerControlCoordinator

_NUMBERS = [
    # (key, name, min, max, step, unit, mode)
    ("trueup_month", "True-Up Month", 1, 12, 1, None, NumberMode.SLIDER),
    ("min_cool_f", "Min Cool Setpoint", 50, 80, 0.5, "°F", NumberMode.BOX),
    ("max_cool_f", "Max Cool Setpoint", 70, 92, 0.5, "°F", NumberMode.BOX),
    ("peak_max_temp_f", "Peak Max Indoor Temp", 70, 90, 0.5, "°F", NumberMode.BOX),
    ("precool_offset_f", "Precool Offset", 0, 8, 0.5, "°F", NumberMode.BOX),
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coord: HAPowerControlCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([_GenericNumber(coord, *spec) for spec in _NUMBERS])


class _GenericNumber(CoordinatorEntity[HAPowerControlCoordinator], NumberEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coord: HAPowerControlCoordinator,
        key: str,
        name: str,
        mn: float,
        mx: float,
        step: float,
        unit: str | None,
        mode: NumberMode,
    ) -> None:
        super().__init__(coord)
        self._key = key
        self._attr_unique_id = f"{coord.entry.entry_id}_{key}"
        self._attr_name = name
        self._attr_native_min_value = mn
        self._attr_native_max_value = mx
        self._attr_native_step = step
        if unit is not None:
            self._attr_native_unit_of_measurement = unit
        self._attr_mode = mode
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coord.entry.entry_id)},
            name="HA Power Control",
            entry_type=DeviceEntryType.SERVICE,
        )
        self._value = float(coord.entry.options.get(key, DEFAULTS[key]))

    @property
    def native_value(self) -> float:
        return self._value

    async def async_set_native_value(self, value: float) -> None:
        self._value = value
        new_options = {**self.coordinator.entry.options, self._key: value}
        self.hass.config_entries.async_update_entry(self.coordinator.entry, options=new_options)
        self.async_write_ha_state()
