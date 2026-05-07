"""HA Power Control integration."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DEFAULTS, DOMAIN, PLATFORMS
from .coordinator import HAPowerControlCoordinator, build_entity_map
from .store import HAPowerControlStore

_LOGGER = logging.getLogger(__name__)


async def _maybe_restore_at_startup(
    hass: HomeAssistant,
    entry: ConfigEntry,
    store: HAPowerControlStore,
    climate_entity: str,
) -> None:
    """If a precool or peak-hold cycle was active across restart, restore originals.

    Spec §6.2: 'if precool_active or peak_hold_active is true and captured_originals
    is set, immediately write originals on coordinator first-tick'.
    """
    cs = store.get_climate_state()
    captured = cs.get("captured_originals")
    if not captured:
        return
    if not (cs.get("precool_active") or cs.get("peak_hold_active")):
        return

    options = {**DEFAULTS, **dict(entry.options)}
    if not options.get("climate_override_enabled", False):
        # User has disabled override; still clear stale flags so next
        # cycle starts clean — but do not write to the thermostat.
        await store.set_climate_state({
            "captured_originals": None,
            "precool_active": False,
            "peak_hold_active": False,
            "precool_ran_this_cycle": False,
            "last_write_record": None,
            "cooldown_until": None,
        })
        return

    from .policy.climate import Action, ActionKind  # local import to avoid cycle
    from .policy.climate_runner import ClimateRunner

    runner = ClimateRunner(
        hass=hass,
        climate_entity=climate_entity,
        save_climate_state=store.set_climate_state,
        dry_run_getter=lambda: bool(options.get("dry_run", True)),
    )

    cleared = {
        "captured_originals": None,
        "precool_active": False,
        "peak_hold_active": False,
        "precool_ran_this_cycle": False,
        "last_write_record": None,
        "cooldown_until": None,
    }
    action = Action(
        kind=ActionKind.RESTORE,
        target_high_f=captured["target_high_f"],
        preset=captured.get("preset"),
        next_persisted=cleared,
        log_reason="startup_restore",
    )
    await runner.apply(
        action,
        datetime.now(UTC),
        current_target_low_f=captured.get("target_low_f"),
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HA Power Control from a config entry."""
    em = build_entity_map(entry.data)
    em.validate_basic()

    store = HAPowerControlStore(hass)
    await store.async_load()

    await _maybe_restore_at_startup(hass, entry, store, em.climate_entity)

    coord = HAPowerControlCoordinator(hass, entry, em, store)
    await coord.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coord

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    coord: HAPowerControlCoordinator = hass.data[DOMAIN][entry.entry_id]
    await coord.async_request_refresh()
