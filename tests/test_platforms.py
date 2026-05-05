"""Platform-registration smoke tests."""

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


def _seed(hass: HomeAssistant) -> None:
    hass.states.async_set(
        "sensor.eagle_200_meter_power_demand",
        "0.5",
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


async def test_setup_creates_expected_sensor_entities(hass: HomeAssistant) -> None:
    _seed(hass)
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
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    expected = [
        "sensor.ha_power_control_net_power",
        "sensor.ha_power_control_export_power",
        "sensor.ha_power_control_mean_indoor_temperature",
        "sensor.ha_power_control_projected_true_up",
    ]
    for eid in expected:
        assert hass.states.get(eid) is not None, f"missing {eid}"


async def test_setup_creates_expected_binary_sensor_entities(hass: HomeAssistant) -> None:
    _seed(hass)
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
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    expected = [
        "binary_sensor.ha_power_control_in_peak_window",
        "binary_sensor.ha_power_control_climate_healthy",
        "binary_sensor.ha_power_control_owns_climate",
        "binary_sensor.ha_power_control_battery_charging",
        "binary_sensor.ha_power_control_battery_discharging",
    ]
    for eid in expected:
        assert hass.states.get(eid) is not None, f"missing {eid}"


async def test_binary_sensor_owns_climate_always_off(hass: HomeAssistant) -> None:
    """OwnsClimateBinary is always False in P1."""
    _seed(hass)
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
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("binary_sensor.ha_power_control_owns_climate")
    assert state is not None
    assert state.state == "off"


async def test_binary_sensor_climate_healthy_with_heat_cool(hass: HomeAssistant) -> None:
    """ClimateHealthyBinary is on when thermostat is in heat_cool with target_high set."""
    _seed(hass)
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
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Thermostat seeded as heat_cool with target_high=76.0 → should be on
    state = hass.states.get("binary_sensor.ha_power_control_climate_healthy")
    assert state is not None
    assert state.state == "on"


# ---------------------------------------------------------------------------
# T14: Switch platform tests
# ---------------------------------------------------------------------------


def _entry_data() -> dict:
    return {
        CONF_NET_W: "sensor.eagle_200_meter_power_demand",
        CONF_NET_IMPORT_KWH: "sensor.eagle_200_total_meter_energy_delivered",
        CONF_NET_EXPORT_KWH: "sensor.eagle_200_total_meter_energy_received",
        CONF_CLIMATE: "climate.thermostat",
        CONF_INDOOR_TEMPS: ["sensor.bedroom_temperature"],
        CONF_NET_W_SIGN: 1,
    }


async def test_switch_entities_created(hass: HomeAssistant) -> None:
    """Setup creates dry_run, climate_override_enabled, and one inclusion switch."""
    _seed(hass)
    entry = MockConfigEntry(domain=DOMAIN, data=_entry_data())
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    expected = [
        "switch.ha_power_control_dry_run",
        "switch.ha_power_control_climate_override_enabled",
        "switch.ha_power_control_include_bedroom_temperature_in_mean",
    ]
    for eid in expected:
        assert hass.states.get(eid) is not None, f"missing {eid}"


async def test_dry_run_default_on(hass: HomeAssistant) -> None:
    """DryRunSwitch defaults to True (ships as opt-in)."""
    _seed(hass)
    entry = MockConfigEntry(domain=DOMAIN, data=_entry_data())
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("switch.ha_power_control_dry_run")
    assert state is not None
    assert state.state == "on"


async def test_climate_override_default_off(hass: HomeAssistant) -> None:
    """ClimateOverrideSwitch defaults to False in P1."""
    _seed(hass)
    entry = MockConfigEntry(domain=DOMAIN, data=_entry_data())
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("switch.ha_power_control_climate_override_enabled")
    assert state is not None
    assert state.state == "off"


async def test_include_indoor_temp_default_on(hass: HomeAssistant) -> None:
    """IncludeIndoorTempSwitch defaults to True (sensor included)."""
    _seed(hass)
    entry = MockConfigEntry(domain=DOMAIN, data=_entry_data())
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("switch.ha_power_control_include_bedroom_temperature_in_mean")
    assert state is not None
    assert state.state == "on"


async def test_dry_run_turn_off(hass: HomeAssistant) -> None:
    """Calling turn_off on DryRunSwitch flips state to off."""
    _seed(hass)
    entry = MockConfigEntry(domain=DOMAIN, data=_entry_data())
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": "switch.ha_power_control_dry_run"},
        blocking=True,
    )
    await hass.async_block_till_done()

    state = hass.states.get("switch.ha_power_control_dry_run")
    assert state is not None
    assert state.state == "off"


async def test_climate_override_turn_on(hass: HomeAssistant) -> None:
    """Calling turn_on on ClimateOverrideSwitch flips state to on."""
    _seed(hass)
    entry = MockConfigEntry(domain=DOMAIN, data=_entry_data())
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": "switch.ha_power_control_climate_override_enabled"},
        blocking=True,
    )
    await hass.async_block_till_done()

    state = hass.states.get("switch.ha_power_control_climate_override_enabled")
    assert state is not None
    assert state.state == "on"


async def test_include_indoor_temp_turn_off_excludes_from_mean(hass: HomeAssistant) -> None:
    """Turning off the inclusion switch marks the sensor excluded in entity_map."""
    _seed(hass)
    entry = MockConfigEntry(domain=DOMAIN, data=_entry_data())
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": "switch.ha_power_control_include_bedroom_temperature_in_mean"},
        blocking=True,
    )
    await hass.async_block_till_done()

    state = hass.states.get("switch.ha_power_control_include_bedroom_temperature_in_mean")
    assert state is not None
    assert state.state == "off"

    # Verify entity_map reflects the exclusion
    from custom_components.ha_power_control.const import DOMAIN as _DOMAIN

    coord = hass.data[_DOMAIN][entry.entry_id]
    assert coord.entity_map.included_indoor_temps["sensor.bedroom_temperature"] is False
