"""Tests for ClimateRunner service-call execution + dry-run gate."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

from homeassistant.core import HomeAssistant

from custom_components.ha_power_control.policy.climate import Action, ActionKind
from custom_components.ha_power_control.policy.climate_runner import ClimateRunner


def _ts() -> datetime:
    return datetime(2026, 5, 6, 14, 0, 0, tzinfo=UTC)


async def test_runner_dry_run_does_not_call_service(hass: HomeAssistant) -> None:
    save_mock = AsyncMock()
    runner = ClimateRunner(
        hass,
        climate_entity="climate.thermostat",
        save_climate_state=save_mock,
        dry_run_getter=lambda: True,
    )
    action = Action(
        kind=ActionKind.PRECOOL_START,
        target_high_f=72.0,
        next_persisted={"precool_active": True},
    )
    calls: list[Any] = []
    hass.services.async_register("climate", "set_temperature", lambda call: calls.append(call))
    await runner.apply(action, _ts(), current_target_low_f=68.0)
    assert calls == []
    save_mock.assert_awaited_once()  # state still persists


async def test_runner_writes_setpoint_when_not_dry_run(hass: HomeAssistant) -> None:
    save_mock = AsyncMock()
    runner = ClimateRunner(
        hass,
        climate_entity="climate.thermostat",
        save_climate_state=save_mock,
        dry_run_getter=lambda: False,
    )
    action = Action(
        kind=ActionKind.PRECOOL_START,
        target_high_f=72.0,
        next_persisted={
            "precool_active": True,
            "captured_originals": {
                "target_high_f": 76.0,
                "target_low_f": 68.0,
                "preset": "home",
                "captured_at": _ts().isoformat(),
            },
        },
    )
    captured: list[dict[str, Any]] = []

    async def fake_service(call):
        captured.append(dict(call.data))

    hass.services.async_register("climate", "set_temperature", fake_service)
    await runner.apply(action, _ts(), current_target_low_f=68.0)
    assert len(captured) == 1
    assert captured[0]["entity_id"] == "climate.thermostat"
    assert captured[0]["target_temp_high"] == 72.0
    assert captured[0]["target_temp_low"] == 68.0  # never touch heat threshold
    # last_write_record persisted
    save_mock.assert_awaited()
    persisted = save_mock.call_args.args[0]
    assert persisted["last_write_record"]["target_high"] == 72.0
    assert persisted["last_write_record"]["written_at"] == _ts().isoformat()


async def test_runner_noop_does_not_call_service(hass: HomeAssistant) -> None:
    save_mock = AsyncMock()
    runner = ClimateRunner(
        hass,
        climate_entity="climate.thermostat",
        save_climate_state=save_mock,
        dry_run_getter=lambda: False,
    )
    action = Action(kind=ActionKind.NOOP, next_persisted={})
    calls: list[Any] = []
    hass.services.async_register("climate", "set_temperature", lambda c: calls.append(c))
    await runner.apply(action, _ts(), current_target_low_f=68.0)
    assert calls == []
    # NOOP still persists in case the policy mutated cooldown_until or similar
    save_mock.assert_awaited_once()
