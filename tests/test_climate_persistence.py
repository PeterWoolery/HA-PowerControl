"""Tests for ClimateState persistence in HAPowerControlStore."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

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
