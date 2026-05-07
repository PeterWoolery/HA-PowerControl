"""Persistence wrapper for HA Power Control."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORE_KEY, STORE_VERSION

_CLIMATE_DEFAULTS: dict[str, Any] = {
    "captured_originals": None,
    "precool_active": False,
    "peak_hold_active": False,
    "precool_ran_this_cycle": False,
    "last_write_record": None,
    "cooldown_until": None,
}


class HAPowerControlStore:
    """Lightweight wrapper around HA Store for cross-restart persistence."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store = Store(hass, STORE_VERSION, STORE_KEY)
        self._cache: dict[str, Any] = {}

    async def async_load(self) -> dict[str, Any]:
        data = await self._store.async_load() or {}
        self._cache = data
        return data

    async def async_save(self, data: dict[str, Any]) -> None:
        self._cache = data
        await self._store.async_save(data)

    @property
    def cache(self) -> dict[str, Any]:
        return self._cache

    # --- Climate state helpers (spec §6.2) ---

    def get_climate_state(self) -> dict[str, Any]:
        """Return persisted climate state with defaults filled in."""
        cs = dict(_CLIMATE_DEFAULTS)
        cs.update(self._cache.get("climate", {}))
        return cs

    async def set_climate_state(self, climate_state: dict[str, Any]) -> None:
        """Persist climate state under the 'climate' subkey."""
        new_cache = {**self._cache, "climate": dict(climate_state)}
        await self.async_save(new_cache)
