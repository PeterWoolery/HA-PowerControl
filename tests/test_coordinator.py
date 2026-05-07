"""Coordinator tests."""

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
from custom_components.ha_power_control.coordinator import (
    HAPowerControlCoordinator,
    build_entity_map,
)
from custom_components.ha_power_control.store import HAPowerControlStore


def _seed_states(hass: HomeAssistant, *, net_w_kw: float = 0.5) -> None:
    hass.states.async_set(
        "sensor.eagle_200_meter_power_demand",
        str(net_w_kw),
        {"unit_of_measurement": "kW", "device_class": "power"},
    )
    hass.states.async_set(
        "sensor.eagle_200_total_meter_energy_delivered",
        "100",
        {"unit_of_measurement": "kWh", "device_class": "energy"},
    )
    hass.states.async_set(
        "sensor.eagle_200_total_meter_energy_received",
        "10",
        {"unit_of_measurement": "kWh", "device_class": "energy"},
    )
    hass.states.async_set(
        "climate.thermostat",
        "heat_cool",
        {
            "target_temp_high": 76.0,
            "target_temp_low": 68.0,
            "current_temperature": 70.4,
            "preset_mode": "home",
        },
    )
    hass.states.async_set(
        "sensor.bedroom_temperature",
        "71.6",
        {"unit_of_measurement": "°F", "device_class": "temperature"},
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


async def test_coordinator_assembles_powerstate_kw_to_w(hass: HomeAssistant) -> None:
    _seed_states(hass, net_w_kw=0.5)
    entry = MockConfigEntry(domain=DOMAIN, data=_entry_data())
    entry.add_to_hass(hass)
    em = build_entity_map(entry.data)
    store = HAPowerControlStore(hass)
    await store.async_load()
    coord = HAPowerControlCoordinator(hass, entry, em, store)
    state = await coord._async_update_data()
    assert state.net_w == 500.0
    assert state.export_w == 0.0
    assert state.mean_indoor_f == 71.6
    assert state.climate.current_f == 70.4
    assert state.tou_period in ("peak", "off_peak")


async def test_coordinator_excludes_toggled_off_indoor_temp(hass: HomeAssistant) -> None:
    _seed_states(hass)
    hass.states.async_set(
        "sensor.elliott_temperature",
        "100",
        {"unit_of_measurement": "°F", "device_class": "temperature"},
    )
    data = _entry_data()
    data[CONF_INDOOR_TEMPS] = ["sensor.bedroom_temperature", "sensor.elliott_temperature"]
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    entry.add_to_hass(hass)
    em = build_entity_map(entry.data)
    em.included_indoor_temps = {
        "sensor.bedroom_temperature": True,
        "sensor.elliott_temperature": False,
    }
    store = HAPowerControlStore(hass)
    await store.async_load()
    coord = HAPowerControlCoordinator(hass, entry, em, store)
    state = await coord._async_update_data()
    assert state.mean_indoor_f == 71.6


async def test_coordinator_export_when_net_w_negative(hass: HomeAssistant) -> None:
    _seed_states(hass, net_w_kw=-2.0)
    entry = MockConfigEntry(domain=DOMAIN, data=_entry_data())
    entry.add_to_hass(hass)
    em = build_entity_map(entry.data)
    store = HAPowerControlStore(hass)
    await store.async_load()
    coord = HAPowerControlCoordinator(hass, entry, em, store)
    state = await coord._async_update_data()
    assert state.net_w == -2000.0
    assert state.export_w == 2000.0


async def test_coordinator_tracks_export_run_seconds(hass: HomeAssistant) -> None:
    _seed_states(hass, net_w_kw=-1.0)  # 1kW export
    entry = MockConfigEntry(domain=DOMAIN, data=_entry_data())
    entry.add_to_hass(hass)
    em = build_entity_map(entry.data)
    store = HAPowerControlStore(hass)
    await store.async_load()
    coord = HAPowerControlCoordinator(hass, entry, em, store)
    s1 = await coord._async_update_data()
    assert s1.export_run_seconds == 0.0
    # Same export sustained — accumulator advances
    s2 = await coord._async_update_data()
    assert s2.export_run_seconds > 0.0


async def test_coordinator_resets_export_run_when_below_threshold(
    hass: HomeAssistant,
) -> None:
    _seed_states(hass, net_w_kw=-1.0)
    entry = MockConfigEntry(domain=DOMAIN, data=_entry_data())
    entry.add_to_hass(hass)
    em = build_entity_map(entry.data)
    store = HAPowerControlStore(hass)
    await store.async_load()
    coord = HAPowerControlCoordinator(hass, entry, em, store)
    await coord._async_update_data()
    # Export collapses
    hass.states.async_set(
        "sensor.eagle_200_meter_power_demand",
        "0.5",
        {"unit_of_measurement": "kW", "device_class": "power"},
    )
    s = await coord._async_update_data()
    assert s.export_run_seconds == 0.0
