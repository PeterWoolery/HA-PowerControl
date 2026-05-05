"""Options flow for HA Power Control — runtime tunables."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import DEFAULTS


def _options_schema(current: dict[str, Any]) -> vol.Schema:
    def _d(k: str) -> Any:
        return current.get(k, DEFAULTS[k])

    return vol.Schema(
        {
            vol.Optional("trueup_month", default=_d("trueup_month")): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=12, step=1)
            ),
            vol.Optional("dry_run", default=_d("dry_run")): selector.BooleanSelector(),
            vol.Optional("min_cool_f", default=_d("min_cool_f")): selector.NumberSelector(
                selector.NumberSelectorConfig(min=50, max=80, step=0.5)
            ),
            vol.Optional("max_cool_f", default=_d("max_cool_f")): selector.NumberSelector(
                selector.NumberSelectorConfig(min=70, max=90, step=0.5)
            ),
        }
    )


class HAPowerControlOptionsFlow(config_entries.OptionsFlow):
    """Options flow — runtime tunables for HA Power Control."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        # Modern HA (2024.x+): base class provides self.config_entry via property;
        # do NOT assign here — the setter logs a deprecation warning (breaks 2025.12).
        pass

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(self.config_entry.options),
        )
