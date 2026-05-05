"""Persistence for climate originals (P2 will extend)."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORE_KEY, STORE_VERSION


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
