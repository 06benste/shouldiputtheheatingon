"""Config and options flow."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import ApiError, HeatingApi
from .const import (
    CONF_ACTIVE,
    CONF_CELL_I,
    CONF_CELL_J,
    CONF_CLIMATE,
    CONF_DEVICE_ID,
    CONF_INDOOR,
    CONF_OUTDOOR,
    CONF_TOKEN,
    CONF_UPDATE_AREA,
    CONF_URL,
    DEFAULT_URL,
    DOMAIN,
    cell_centre,
    cell_for,
)

ENTITY_KEYS = (CONF_CLIMATE, CONF_INDOOR, CONF_OUTDOOR, CONF_ACTIVE)


def _entity_fields() -> dict:
    temp = EntitySelector(EntitySelectorConfig(domain="sensor", device_class="temperature"))
    return {
        vol.Required(CONF_CLIMATE): EntitySelector(EntitySelectorConfig(domain="climate")),
        vol.Optional(CONF_INDOOR): temp,
        vol.Required(CONF_OUTDOOR): temp,
        vol.Optional(CONF_ACTIVE): EntitySelector(
            EntitySelectorConfig(domain=["binary_sensor", "switch", "input_boolean"])
        ),
    }


def _area_text(i: int, j: int) -> str:
    lat, lon = cell_centre(i, j)
    return f"{lat}, {lon}"


class HeatingConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        lat, lon = self.hass.config.latitude, self.hass.config.longitude
        if lat is None or lon is None or (lat == 0 and lon == 0):
            return self.async_abort(reason="no_location")
        cell_i, cell_j = cell_for(lat, lon)

        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_URL].rstrip("/")
            api = HeatingApi(async_get_clientsession(self.hass), url)
            try:
                reg = await api.register(cell_i, cell_j)
            except ApiError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(reg["device_id"])
                return self.async_create_entry(
                    title="Should I put the heating on?",
                    data={
                        CONF_URL: url,
                        CONF_TOKEN: reg["token"],
                        CONF_DEVICE_ID: reg["device_id"],
                        CONF_CELL_I: cell_i,
                        CONF_CELL_J: cell_j,
                    },
                    options={k: user_input[k] for k in ENTITY_KEYS if user_input.get(k)},
                )

        schema = vol.Schema({
            vol.Required(CONF_URL, default=DEFAULT_URL): TextSelector(TextSelectorConfig(type=TextSelectorType.URL)),
            **_entity_fields(),
        })
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
            description_placeholders={"area": _area_text(cell_i, cell_j)},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return HeatingOptionsFlow()


class HeatingOptionsFlow(OptionsFlow):
    """Change which entities are shared, or move the home to a new area."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self.config_entry
        if user_input is not None:
            if user_input.get(CONF_UPDATE_AREA):
                cell_i, cell_j = cell_for(self.hass.config.latitude, self.hass.config.longitude)
                self.hass.config_entries.async_update_entry(
                    entry, data={**entry.data, CONF_CELL_I: cell_i, CONF_CELL_J: cell_j}
                )
            return self.async_create_entry(data={k: user_input[k] for k in ENTITY_KEYS if user_input.get(k)})

        schema = vol.Schema({
            **_entity_fields(),
            vol.Optional(CONF_UPDATE_AREA, default=False): BooleanSelector(),
        })
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, dict(entry.options)),
            description_placeholders={"area": _area_text(entry.data[CONF_CELL_I], entry.data[CONF_CELL_J])},
        )
