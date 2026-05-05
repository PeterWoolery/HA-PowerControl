"""Binary sensor platform: in_peak_window, climate_healthy."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
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
    async_add_entities(
        [
            InPeakWindowBinary(coord),
            ClimateHealthyBinary(coord),
            OwnsClimateBinary(coord),
            BatteryChargingBinary(coord),
            BatteryDischargingBinary(coord),
        ]
    )


class _Base(CoordinatorEntity[HAPowerControlCoordinator], BinarySensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coord: HAPowerControlCoordinator, key: str, name: str) -> None:
        super().__init__(coord)
        self._attr_unique_id = f"{coord.entry.entry_id}_{key}"
        self._attr_name = name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coord.entry.entry_id)},
            name="HA Power Control",
            entry_type=DeviceEntryType.SERVICE,
        )


class InPeakWindowBinary(_Base):
    def __init__(self, c: HAPowerControlCoordinator) -> None:
        super().__init__(c, "in_peak_window", "In Peak Window")

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.in_peak_window if self.coordinator.data else False


class ClimateHealthyBinary(_Base):
    def __init__(self, c: HAPowerControlCoordinator) -> None:
        super().__init__(c, "climate_healthy", "Climate Healthy")

    @property
    def is_on(self) -> bool:
        d = self.coordinator.data
        if d is None:
            return False
        return d.climate.hvac_mode == "heat_cool" and d.climate.target_high_f is not None


class OwnsClimateBinary(_Base):
    """P1: always off (no climate writes yet). P2 will compute from store flags."""

    def __init__(self, c: HAPowerControlCoordinator) -> None:
        super().__init__(c, "owns_climate", "Owns Climate")

    @property
    def is_on(self) -> bool:
        return False


class BatteryChargingBinary(_Base):
    def __init__(self, c: HAPowerControlCoordinator) -> None:
        super().__init__(c, "battery_charging", "Battery Charging")

    @property
    def is_on(self) -> bool:
        d = self.coordinator.data
        return bool(d and d.battery and d.battery.charging)


class BatteryDischargingBinary(_Base):
    def __init__(self, c: HAPowerControlCoordinator) -> None:
        super().__init__(c, "battery_discharging", "Battery Discharging")

    @property
    def is_on(self) -> bool:
        d = self.coordinator.data
        return bool(d and d.battery and d.battery.discharging)
