"""Async runner that translates Action → HA service calls + Store writes."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant

from .climate import Action, ActionKind

_LOGGER = logging.getLogger(__name__)

_WRITING_KINDS = {
    ActionKind.PRECOOL_START,
    ActionKind.PEAK_HOLD_START,
    ActionKind.RESTORE,
}


class ClimateRunner:
    """Apply policy Actions to HA, gated by dry_run."""

    def __init__(
        self,
        hass: HomeAssistant,
        climate_entity: str,
        save_climate_state: Callable[[dict[str, Any]], Awaitable[None]],
        dry_run_getter: Callable[[], bool],
    ) -> None:
        self._hass = hass
        self._climate_entity = climate_entity
        self._save = save_climate_state
        self._dry_run_getter = dry_run_getter

    async def apply(
        self,
        action: Action,
        ts: datetime,
        *,
        current_target_low_f: float | None,
    ) -> None:
        """Execute Action, persist next_persisted regardless."""
        persisted = dict(action.next_persisted)

        write_attempted = action.kind in _WRITING_KINDS and action.target_high_f is not None
        if write_attempted and not self._dry_run_getter():
            await self._write_setpoint(
                target_high_f=action.target_high_f,
                target_low_f=current_target_low_f,
            )
            persisted["last_write_record"] = {
                "target_high": action.target_high_f,
                "preset": action.preset,
                "written_at": ts.isoformat(),
            }
            _LOGGER.info(
                "climate_runner: %s target_high=%.1f reason=%s",
                action.kind.value,
                action.target_high_f,
                action.log_reason,
            )
        elif write_attempted:
            _LOGGER.info(
                "climate_runner: DRY-RUN suppressed %s target_high=%.1f reason=%s",
                action.kind.value,
                action.target_high_f,
                action.log_reason,
            )

        await self._save(persisted)

    async def _write_setpoint(
        self,
        *,
        target_high_f: float,
        target_low_f: float | None,
    ) -> None:
        """Write target_temp_high while preserving target_temp_low.

        IMPORTANT (spec §6.2): NEVER manipulate target_temp_low.
        We pass it through unchanged so HA's heat_cool service does not
        coerce a default heat threshold that might activate the furnace.

        Note: target_high_f has already been clamped to [min_cool_f, max_cool_f]
        by the policy. If the user's original setpoint was outside those bounds,
        a RESTORE will write the clamped value rather than the literal original.
        Spec §7.1 mandates this safety bound.
        """
        data: dict[str, Any] = {
            "entity_id": self._climate_entity,
            "target_temp_high": target_high_f,
        }
        if target_low_f is not None:
            data["target_temp_low"] = target_low_f
        await self._hass.services.async_call("climate", "set_temperature", data, blocking=True)
