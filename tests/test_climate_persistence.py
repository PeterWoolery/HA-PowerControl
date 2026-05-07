"""Tests for ClimateState persistence in HAPowerControlStore."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_power_control.const import (
    CONF_CLIMATE,
    CONF_INDOOR_TEMPS,
    CONF_NET_EXPORT_KWH,
    CONF_NET_IMPORT_KWH,
    CONF_NET_W,
    CONF_NET_W_SIGN,
    DOMAIN,
    STORE_KEY,
    STORE_VERSION,
)
from custom_components.ha_power_control.store import HAPowerControlStore


async def test_get_climate_state_returns_defaults_when_empty(
    hass: HomeAssistant,
) -> None:
    store = HAPowerControlStore(hass)
    await store.async_load()
    cs = store.get_climate_state()
    assert cs == {
        "captured_originals": None,
        "precool_active": False,
        "peak_hold_active": False,
        "precool_ran_this_cycle": False,
        "last_write_record": None,
        "cooldown_until": None,
    }


async def test_set_and_get_climate_state_round_trips(hass: HomeAssistant) -> None:
    store = HAPowerControlStore(hass)
    await store.async_load()
    payload = {
        "captured_originals": {
            "target_high_f": 76.0,
            "target_low_f": 68.0,
            "preset": "home",
            "captured_at": "2026-05-06T15:00:00+00:00",
        },
        "precool_active": True,
        "peak_hold_active": False,
        "precool_ran_this_cycle": True,
        "last_write_record": {
            "target_high": 72.0,
            "preset": "home",
            "written_at": "2026-05-06T15:00:30+00:00",
        },
        "cooldown_until": None,
    }
    await store.set_climate_state(payload)
    assert store.get_climate_state() == payload

    # Round-trip across a fresh load
    store2 = HAPowerControlStore(hass)
    await store2.async_load()
    assert store2.get_climate_state() == payload


# ---------------------------------------------------------------------------
# Task 13: Restore-on-startup tests
# ---------------------------------------------------------------------------

def _seed_min_states(hass) -> None:
    hass.states.async_set(
        "sensor.eagle_200_meter_power_demand", "0",
        {"unit_of_measurement": "kW", "device_class": "power"},
    )
    hass.states.async_set(
        "sensor.eagle_200_total_meter_energy_delivered", "0",
        {"unit_of_measurement": "kWh"},
    )
    hass.states.async_set(
        "sensor.eagle_200_total_meter_energy_received", "0",
        {"unit_of_measurement": "kWh"},
    )
    hass.states.async_set(
        "climate.thermostat", "heat_cool",
        {"target_temp_high": 72.0, "target_temp_low": 68.0,
         "current_temperature": 73.0, "preset_mode": "home"},
    )
    hass.states.async_set(
        "sensor.bedroom_temperature", "73.0",
        {"unit_of_measurement": "°F"},
    )


async def _seed_store(hass, climate_payload: dict) -> None:
    """Pre-populate the HA Store under our domain key via HA's Store API.

    Writing through the Store API ensures the StorageManager cache is
    invalidated so subsequent Store instances read fresh data from disk.
    """
    seeder: Store = Store(hass, STORE_VERSION, STORE_KEY)
    await seeder.async_save({"climate": climate_payload})


async def test_restore_on_startup_when_peak_hold_active(hass) -> None:
    _seed_min_states(hass)
    await _seed_store(hass, {
        "captured_originals": {
            "target_high_f": 76.0, "target_low_f": 68.0,
            "preset": "home", "captured_at": "2026-05-06T15:00:00+00:00",
        },
        "precool_active": False,
        "peak_hold_active": True,
        "precool_ran_this_cycle": True,
        "last_write_record": None,
        "cooldown_until": None,
    })

    calls: list[dict] = []

    async def fake_service(call):
        calls.append(dict(call.data))

    hass.services.async_register("climate", "set_temperature", fake_service)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_NET_W: "sensor.eagle_200_meter_power_demand",
            CONF_NET_IMPORT_KWH: "sensor.eagle_200_total_meter_energy_delivered",
            CONF_NET_EXPORT_KWH: "sensor.eagle_200_total_meter_energy_received",
            CONF_CLIMATE: "climate.thermostat",
            CONF_INDOOR_TEMPS: ["sensor.bedroom_temperature"],
            CONF_NET_W_SIGN: 1,
        },
        options={"dry_run": False, "climate_override_enabled": True},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Restore call must have fired with original target_high_f
    assert any(c.get("target_temp_high") == 76.0 for c in calls)
