"""Config-flow tests."""

from __future__ import annotations

from homeassistant import config_entries, data_entry_flow
from homeassistant.core import HomeAssistant

from custom_components.ha_power_control.const import (
    CONF_CLIMATE,
    CONF_INDOOR_TEMPS,
    CONF_NET_EXPORT_KWH,
    CONF_NET_IMPORT_KWH,
    CONF_NET_W,
    CONF_NET_W_SIGN,
    DOMAIN,
)


async def test_user_step_creates_entry_with_minimal_input(hass: HomeAssistant) -> None:
    """Happy path: user fills required fields, entry is created."""
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
        {"target_temp_high": 76.0, "target_temp_low": 68.0, "current_temperature": 70.0},
    )
    hass.states.async_set(
        "sensor.bedroom_temperature",
        "70.0",
        {"unit_of_measurement": "°F", "device_class": "temperature"},
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == data_entry_flow.FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NET_W: "sensor.eagle_200_meter_power_demand",
            CONF_NET_IMPORT_KWH: "sensor.eagle_200_total_meter_energy_delivered",
            CONF_NET_EXPORT_KWH: "sensor.eagle_200_total_meter_energy_received",
            CONF_CLIMATE: "climate.thermostat",
            CONF_INDOOR_TEMPS: ["sensor.bedroom_temperature"],
            CONF_NET_W_SIGN: 1,
        },
    )
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY


async def test_user_step_rejects_climate_not_in_heat_cool_mode(hass: HomeAssistant) -> None:
    hass.states.async_set("sensor.x", "0", {"unit_of_measurement": "kW"})
    hass.states.async_set("sensor.y", "0", {"unit_of_measurement": "kWh"})
    hass.states.async_set("sensor.z", "0", {"unit_of_measurement": "kWh"})
    hass.states.async_set("climate.bad", "off", {})
    hass.states.async_set("sensor.t", "70", {"device_class": "temperature"})

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NET_W: "sensor.x",
            CONF_NET_IMPORT_KWH: "sensor.y",
            CONF_NET_EXPORT_KWH: "sensor.z",
            CONF_CLIMATE: "climate.bad",
            CONF_INDOOR_TEMPS: ["sensor.t"],
            CONF_NET_W_SIGN: 1,
        },
    )
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert "climate" in result["errors"]
