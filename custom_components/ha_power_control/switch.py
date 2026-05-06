"""Switch platform: per-temp-sensor inclusion + dry_run + climate_override (off in P1)."""

from __future__ import annotations

import re
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULTS, DOMAIN
from .coordinator import HAPowerControlCoordinator


def _slug(eid: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", eid.split(".", 1)[1].lower()).strip("_")


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coord: HAPowerControlCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SwitchEntity] = [
        DryRunSwitch(coord),
        ClimateOverrideSwitch(coord),
    ]
    for eid in coord.entity_map.indoor_temp_entities:
        entities.append(IncludeIndoorTempSwitch(coord, eid))
    async_add_entities(entities)


class _Base(CoordinatorEntity[HAPowerControlCoordinator], SwitchEntity):
    _attr_has_entity_name = True

    def __init__(self, coord: HAPowerControlCoordinator) -> None:
        super().__init__(coord)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coord.entry.entry_id)},
            name="HA Power Control",
            entry_type=DeviceEntryType.SERVICE,
        )


class IncludeIndoorTempSwitch(_Base):
    def __init__(self, coord: HAPowerControlCoordinator, source_eid: str) -> None:
        super().__init__(coord)
        self._source_eid = source_eid
        slug = _slug(source_eid)
        self._attr_unique_id = f"{coord.entry.entry_id}_include_{slug}"
        friendly = source_eid.split(".", 1)[1].replace("_", " ").title()
        self._attr_name = f"Include {friendly} in Mean"

    @property
    def is_on(self) -> bool:
        return self.coordinator.entity_map.included_indoor_temps.get(self._source_eid, True)

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.coordinator.entity_map.included_indoor_temps[self._source_eid] = True
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.coordinator.entity_map.included_indoor_temps[self._source_eid] = False
        await self.coordinator.async_request_refresh()


class _PersistedFlagSwitch(_Base):
    """Boolean switch whose state is persisted in entry.options[key]."""

    _option_key: str
    _default: bool

    def __init__(
        self, coord: HAPowerControlCoordinator, key: str, name: str, default: bool
    ) -> None:
        super().__init__(coord)
        self._option_key = key
        self._default = default
        self._attr_unique_id = f"{coord.entry.entry_id}_{key}"
        self._attr_name = name

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.entry.options.get(self._option_key, self._default))

    async def _persist(self, value: bool) -> None:
        new_options = {**self.coordinator.entry.options, self._option_key: value}
        self.hass.config_entries.async_update_entry(self.coordinator.entry, options=new_options)
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._persist(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._persist(False)


class DryRunSwitch(_PersistedFlagSwitch):
    def __init__(self, coord: HAPowerControlCoordinator) -> None:
        super().__init__(coord, "dry_run", "Dry Run", DEFAULTS["dry_run"])


class ClimateOverrideSwitch(_PersistedFlagSwitch):
    """Master enable for climate writes. Default OFF."""

    def __init__(self, coord: HAPowerControlCoordinator) -> None:
        super().__init__(
            coord,
            "climate_override_enabled",
            "Climate Override Enabled",
            DEFAULTS["climate_override_enabled"],
        )
