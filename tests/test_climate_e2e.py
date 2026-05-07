"""End-to-end: simulated tick sequence through coordinator + runner."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

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

LA = ZoneInfo("America/Los_Angeles")


def _seed(hass: HomeAssistant) -> None:
    hass.states.async_set(
        "sensor.eagle_200_meter_power_demand",
        "-1.5",
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
            "current_temperature": 78.0,
            "preset_mode": "home",
        },
    )
    hass.states.async_set(
        "sensor.bedroom_temperature",
        "78.0",
        {"unit_of_measurement": "°F"},
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


async def test_full_cycle_precool_then_peak_hold_then_restore(
    hass: HomeAssistant,
) -> None:
    _seed(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=_entry_data(),
        options={"dry_run": False, "climate_override_enabled": True},
    )
    entry.add_to_hass(hass)

    calls: list[dict] = []

    async def fake_service(call):
        calls.append(dict(call.data))
        # Reflect the write back into state so subsequent ticks see new target_high.
        cur = hass.states.get("climate.thermostat")
        attrs = dict(cur.attributes) if cur else {}
        attrs["target_temp_high"] = call.data["target_temp_high"]
        attrs["target_temp_low"] = call.data.get(
            "target_temp_low", attrs.get("target_temp_low", 68.0)
        )
        hass.states.async_set("climate.thermostat", "heat_cool", attrs)

    hass.services.async_register("climate", "set_temperature", fake_service)

    # Pin hass timezone so DEFAULT_TIME_ZONE-based conversions are deterministic
    # on any CI runner regardless of system locale.
    await hass.config.async_set_time_zone("America/Los_Angeles")

    # Pre-peak Wednesday afternoon — 4:30pm LA, 30 min before peak (5pm).
    # Use tz-aware datetimes so .astimezone(DEFAULT_TIME_ZONE) is deterministic
    # regardless of the system/CI timezone.
    base = datetime(2026, 5, 6, 16, 30, 0, tzinfo=LA)

    with patch(
        "custom_components.ha_power_control.coordinator.dt_util.utcnow",
        return_value=base,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # First tick — sustained-export needs ≥10 min; this is t=0 so no precool yet.
    coord = hass.data[DOMAIN][entry.entry_id]
    assert calls == []  # no setpoint write on first tick

    # Advance simulated time +700s (>10 min) and tick again.
    # Use async_refresh() (immediate, non-debounced) so the fetch runs while
    # the patch is still active and dt_util.utcnow returns the mocked value.
    with patch(
        "custom_components.ha_power_control.coordinator.dt_util.utcnow",
        return_value=base + timedelta(seconds=700),
    ):
        await coord.async_refresh()
        await hass.async_block_till_done()
    # Precool should have fired: target = peak_max_temp_f - precool_offset_f = 80-4 = 76 - 4 = 72
    assert any(c.get("target_temp_high") == 72.0 for c in calls), (
        f"expected precool write to 72.0, got {calls}"
    )

    # Advance to peak window (5pm); peak-hold should fire
    with patch(
        "custom_components.ha_power_control.coordinator.dt_util.utcnow",
        return_value=datetime(2026, 5, 6, 17, 0, 30, tzinfo=LA),
    ):
        await coord.async_refresh()
        await hass.async_block_till_done()
    assert any(c.get("target_temp_high") == 80.0 for c in calls)

    # Advance past peak end (8pm); restore originals
    with patch(
        "custom_components.ha_power_control.coordinator.dt_util.utcnow",
        return_value=datetime(2026, 5, 6, 20, 0, 30, tzinfo=LA),
    ):
        await coord.async_refresh()
        await hass.async_block_till_done()
    # Final write must restore 76.0
    assert calls[-1].get("target_temp_high") == 76.0, (
        f"expected restore write to 76.0 as last call, got {calls}"
    )
