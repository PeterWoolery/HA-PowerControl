"""Options-flow tests."""

from __future__ import annotations

from homeassistant import data_entry_flow
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_power_control.const import DOMAIN


async def test_options_flow_changes_trueup_month(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={"x": 1}, options={})
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == data_entry_flow.FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"trueup_month": 7, "dry_run": True, "min_cool_f": 65, "max_cool_f": 82},
    )
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"]["trueup_month"] == 7


async def test_options_flow_defaults_on_empty_options(hass: HomeAssistant) -> None:
    """Schema defaults applied when options is empty."""
    entry = MockConfigEntry(domain=DOMAIN, data={"x": 1}, options={})
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    # Schema was built without error — DEFAULTS keys exist and schema is valid.
    assert result["step_id"] == "init"
