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
    """OwnsClimateBinary is off when store flags are all false (default)."""
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


# ---------------------------------------------------------------------------
# T15: Number + Select platform tests
# ---------------------------------------------------------------------------


async def test_number_entities_created(hass: HomeAssistant) -> None:
    """Setup creates all four P1 number tuneables."""
    _seed(hass)
    entry = MockConfigEntry(domain=DOMAIN, data=_entry_data())
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    expected = [
        "number.ha_power_control_true_up_month",
        "number.ha_power_control_min_cool_setpoint",
        "number.ha_power_control_max_cool_setpoint",
        "number.ha_power_control_peak_max_indoor_temp",
    ]
    for eid in expected:
        assert hass.states.get(eid) is not None, f"missing {eid}"


async def test_number_trueup_month_default(hass: HomeAssistant) -> None:
    """True-Up Month defaults to 6 (June)."""
    _seed(hass)
    entry = MockConfigEntry(domain=DOMAIN, data=_entry_data())
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("number.ha_power_control_true_up_month")
    assert state is not None
    assert float(state.state) == 6.0


async def test_number_min_cool_default(hass: HomeAssistant) -> None:
    """Min Cool Setpoint defaults to 65.0 °F."""
    _seed(hass)
    entry = MockConfigEntry(domain=DOMAIN, data=_entry_data())
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("number.ha_power_control_min_cool_setpoint")
    assert state is not None
    assert float(state.state) == 65.0


async def test_number_set_value(hass: HomeAssistant) -> None:
    """Setting a number value persists to config entry options."""
    _seed(hass)
    entry = MockConfigEntry(domain=DOMAIN, data=_entry_data())
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.ha_power_control_true_up_month", "value": 9},
        blocking=True,
    )
    await hass.async_block_till_done()

    state = hass.states.get("number.ha_power_control_true_up_month")
    assert state is not None
    assert float(state.state) == 9.0
    # options updated
    assert entry.options.get("trueup_month") == 9.0


async def test_select_entity_created(hass: HomeAssistant) -> None:
    """Setup creates the operating_mode select entity."""
    _seed(hass)
    entry = MockConfigEntry(domain=DOMAIN, data=_entry_data())
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("select.ha_power_control_operating_mode")
    assert state is not None


async def test_select_operating_mode_default(hass: HomeAssistant) -> None:
    """OperatingModeSelect defaults to 'auto'."""
    _seed(hass)
    entry = MockConfigEntry(domain=DOMAIN, data=_entry_data())
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("select.ha_power_control_operating_mode")
    assert state is not None
    assert state.state == "auto"


async def test_select_operating_mode_change(hass: HomeAssistant) -> None:
    """Selecting a new mode updates state and config entry options."""
    _seed(hass)
    entry = MockConfigEntry(domain=DOMAIN, data=_entry_data())
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        "select",
        "select_option",
        {
            "entity_id": "select.ha_power_control_operating_mode",
            "option": "peak_shave_only",
        },
        blocking=True,
    )
    await hass.async_block_till_done()

    state = hass.states.get("select.ha_power_control_operating_mode")
    assert state is not None
    assert state.state == "peak_shave_only"
    assert entry.options.get("operating_mode") == "peak_shave_only"


# ---------------------------------------------------------------------------
# T16: Button platform tests
# ---------------------------------------------------------------------------


async def test_button_entity_created(hass: HomeAssistant) -> None:
    """Setup creates the snapshot_state button entity."""
    _seed(hass)
    entry = MockConfigEntry(domain=DOMAIN, data=_entry_data())
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("button.ha_power_control_snapshot_state")
    assert state is not None


async def test_button_press_writes_snapshot(hass: HomeAssistant, tmp_path) -> None:
    """Pressing snapshot_state writes a JSON file to the snapshots dir."""
    import json as _json

    _seed(hass)
    entry = MockConfigEntry(domain=DOMAIN, data=_entry_data())
    entry.add_to_hass(hass)

    # Redirect hass.config.path to tmp_path so we don't need the real FS
    hass.config.config_dir = str(tmp_path)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": "button.ha_power_control_snapshot_state"},
        blocking=True,
    )
    await hass.async_block_till_done()

    snap_dir = tmp_path / "ha_power_control" / "snapshots"
    files = list(snap_dir.glob("snapshot_*.json"))
    assert len(files) == 1, f"expected 1 snapshot file, got {files}"

    data = _json.loads(files[0].read_text())
    assert "ts" in data
    assert "net_w" in data
    assert "battery" in data


async def test_button_press_no_data_is_noop(hass: HomeAssistant, tmp_path) -> None:
    """Pressing snapshot_state when coordinator has no data is a safe no-op."""
    _seed(hass)
    entry = MockConfigEntry(domain=DOMAIN, data=_entry_data())
    entry.add_to_hass(hass)

    hass.config.config_dir = str(tmp_path)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Clear coordinator data to simulate unavailability
    coord = hass.data[DOMAIN][entry.entry_id]
    coord.data = None

    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": "button.ha_power_control_snapshot_state"},
        blocking=True,
    )
    await hass.async_block_till_done()

    snap_dir = tmp_path / "ha_power_control" / "snapshots"
    assert not snap_dir.exists() or list(snap_dir.glob("snapshot_*.json")) == []
