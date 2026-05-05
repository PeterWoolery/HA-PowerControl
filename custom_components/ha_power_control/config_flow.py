"""Config flow for HA Power Control."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector

from .const import (
    CONF_BATTERY_CHARGE_SWITCH,
    CONF_BATTERY_CHARGE_W,
    CONF_BATTERY_DISCHARGE_W,
    CONF_BATTERY_SOC,
    CONF_CLIMATE,
    CONF_INDOOR_TEMPS,
    CONF_NET_EXPORT_KWH,
    CONF_NET_IMPORT_KWH,
    CONF_NET_W,
    CONF_NET_W_SIGN,
    CONF_SOLAR_W,
    DOMAIN,
)
from .entity_map import EntityMap, ValidationError


def _user_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_NET_W): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="power")
            ),
            vol.Required(CONF_NET_IMPORT_KWH): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="energy")
            ),
            vol.Required(CONF_NET_EXPORT_KWH): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="energy")
            ),
            vol.Optional(CONF_SOLAR_W): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="power")
            ),
            vol.Required(CONF_CLIMATE): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="climate")
            ),
            vol.Required(CONF_INDOOR_TEMPS): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor", device_class="temperature", multiple=True
                )
            ),
            vol.Optional(CONF_BATTERY_SOC): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="battery")
            ),
            vol.Optional(CONF_BATTERY_CHARGE_W): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="power")
            ),
            vol.Optional(CONF_BATTERY_DISCHARGE_W): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="power")
            ),
            vol.Optional(CONF_BATTERY_CHARGE_SWITCH): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="switch")
            ),
            vol.Required(CONF_NET_W_SIGN, default=1): vol.In([1, -1]),
        }
    )


def _validate_climate(hass: HomeAssistant, entity_id: str) -> str | None:
    state = hass.states.get(entity_id)
    if state is None:
        return "climate_unavailable"
    if state.state != "heat_cool":
        return "climate_not_heat_cool"
    if state.attributes.get("target_temp_high") is None:
        return "climate_missing_target_high"
    return None


class HAPowerControlConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            climate_err = _validate_climate(self.hass, user_input[CONF_CLIMATE])
            if climate_err:
                errors["climate"] = climate_err
            try:
                em = EntityMap(
                    net_w_entity=user_input[CONF_NET_W],
                    net_import_kwh_entity=user_input[CONF_NET_IMPORT_KWH],
                    net_export_kwh_entity=user_input[CONF_NET_EXPORT_KWH],
                    climate_entity=user_input[CONF_CLIMATE],
                    indoor_temp_entities=user_input[CONF_INDOOR_TEMPS],
                    net_w_sign=user_input.get(CONF_NET_W_SIGN, 1),
                    solar_w_entity=user_input.get(CONF_SOLAR_W),
                    battery_soc_entity=user_input.get(CONF_BATTERY_SOC),
                    battery_charge_w_entity=user_input.get(CONF_BATTERY_CHARGE_W),
                    battery_discharge_w_entity=user_input.get(CONF_BATTERY_DISCHARGE_W),
                    battery_charge_switch_entity=user_input.get(CONF_BATTERY_CHARGE_SWITCH),
                )
                em.validate_basic()
            except ValidationError as e:
                errors["base"] = str(e)

            if not errors:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="HA Power Control", data=user_input)

        return self.async_show_form(step_id="user", data_schema=_user_schema(), errors=errors)
