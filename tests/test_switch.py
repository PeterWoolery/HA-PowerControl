"""Switch persistence tests."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_power_control.const import (
    CONF_CLIMATE,
    CONF_INDOOR_TEMPS,
    CONF_NET_EXPORT_KWH,
    CONF_NET_IMPORT_KWH,
    CONF_NET_W,
    CONF_NET_W_SIGN,
    DOMAIN,
)


def _entry_data() -> dict:
    return {
        CONF_NET_W: "sensor.eagle_200_meter_power_demand",
        CONF_NET_IMPORT_KWH: "sensor.eagle_200_total_meter_energy_delivered",
        CONF_NET_EXPORT_KWH: "sensor.eagle_200_total_meter_energy_received",
        CONF_CLIMATE: "climate.thermostat",
        CONF_INDOOR_TEMPS: ["sensor.bedroom_temperature"],
        CONF_NET_W_SIGN: 1,
    }


def _seed_min_states(hass: HomeAssistant) -> None:
    hass.states.async_set(
        "sensor.eagle_200_meter_power_demand",
        "0",
        {"unit_of_measurement": "kW", "device_class": "power"},
    )
    hass.states.async_set(
        "sensor.eagle_200_total_meter_energy_delivered",
        "0",
        {"unit_of_measurement": "kWh"},
    )
    hass.states.async_set(
        "sensor.eagle_200_total_meter_energy_received",
        "0",
        {"unit_of_measurement": "kWh"},
    )
    hass.states.async_set(
        "climate.thermostat",
        "heat_cool",
        {
            "target_temp_high": 76.0,
            "target_temp_low": 68.0,
            "current_temperature": 72.0,
            "preset_mode": "home",
        },
    )
    hass.states.async_set(
        "sensor.bedroom_temperature",
        "72.0",
        {"unit_of_measurement": "°F"},
    )


async def test_dry_run_switch_persists_to_options(hass: HomeAssistant) -> None:
    _seed_min_states(hass)
    entry = MockConfigEntry(domain=DOMAIN, data=_entry_data(), options={"dry_run": True})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": "switch.ha_power_control_dry_run"},
        blocking=True,
    )
    assert hass.config_entries.async_get_entry(entry.entry_id).options["dry_run"] is False


async def test_climate_override_switch_persists_to_options(hass: HomeAssistant) -> None:
    _seed_min_states(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=_entry_data(),
        options={"climate_override_enabled": False},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": "switch.ha_power_control_climate_override_enabled"},
        blocking=True,
    )
    assert (
        hass.config_entries.async_get_entry(entry.entry_id).options["climate_override_enabled"]
        is True
    )


async def test_dry_run_switch_round_trips_off_then_on(hass: HomeAssistant) -> None:
    _seed_min_states(hass)
    entry = MockConfigEntry(domain=DOMAIN, data=_entry_data(), options={"dry_run": True})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Initial: True
    assert hass.config_entries.async_get_entry(entry.entry_id).options["dry_run"] is True

    # → False
    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": "switch.ha_power_control_dry_run"},
        blocking=True,
    )
    assert hass.config_entries.async_get_entry(entry.entry_id).options["dry_run"] is False

    # → True
    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": "switch.ha_power_control_dry_run"},
        blocking=True,
    )
    assert hass.config_entries.async_get_entry(entry.entry_id).options["dry_run"] is True
