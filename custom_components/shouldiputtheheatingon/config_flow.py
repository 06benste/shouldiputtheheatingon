"""Config and options flow."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.climate import ATTR_HVAC_ACTION
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import ApiError, HeatingApi
from .const import (
    API_URL,
    CONF_ACTIVE,
    CONF_ACTIVE_ABOVE,
    CONF_CELL_I,
    CONF_CELL_J,
    CONF_CLIMATE,
    CONF_DEVICE_ID,
    CONF_INDOOR,
    CONF_ON_MEANS,
    CONF_OUTDOOR,
    CONF_TOKEN,
    CONF_UPDATE_AREA,
    DOMAIN,
    ON_MEANS_HEATING,
    ON_MEANS_SWITCHED_ON,
    cell_centre,
    cell_for,
)

ENTITY_KEYS = (CONF_CLIMATE, CONF_INDOOR, CONF_OUTDOOR, CONF_ACTIVE, CONF_ACTIVE_ABOVE)


def _on_means_field(default: str) -> dict:
    return {
        vol.Required(CONF_ON_MEANS, default=default): SelectSelector(
            SelectSelectorConfig(
                options=[ON_MEANS_SWITCHED_ON, ON_MEANS_HEATING],
                mode=SelectSelectorMode.LIST,
                translation_key=CONF_ON_MEANS,
            )
        ),
    }


def _entity_fields(on_means: str) -> dict:
    temp = EntitySelector(EntitySelectorConfig(domain="sensor", device_class="temperature"))
    fields = {
        vol.Required(CONF_CLIMATE): EntitySelector(EntitySelectorConfig(domain="climate", multiple=True)),
        vol.Optional(CONF_INDOOR): temp,
        vol.Required(CONF_OUTDOOR): temp,
    }
    if on_means == ON_MEANS_HEATING:
        fields[vol.Optional(CONF_ACTIVE)] = EntitySelector(
            EntitySelectorConfig(domain=["binary_sensor", "switch", "input_boolean", "sensor"], multiple=True)
        )
        fields[vol.Optional(CONF_ACTIVE_ABOVE)] = NumberSelector(
            NumberSelectorConfig(mode=NumberSelectorMode.BOX, step="any")
        )
    return fields


def _validate_entities(hass: HomeAssistant, on_means: str, user_input: dict[str, Any]) -> dict[str, str]:
    """Actively heating needs either a sensor or a thermostat that reports what it's doing."""
    if on_means != ON_MEANS_HEATING or user_input.get(CONF_ACTIVE):
        return {}
    for entity_id in user_input[CONF_CLIMATE]:
        state = hass.states.get(entity_id)
        if state is not None and state.attributes.get(ATTR_HVAC_ACTION) is not None:
            return {}
    return {CONF_ACTIVE: "no_hvac_action"}


def _entity_options(on_means: str, user_input: dict[str, Any]) -> dict[str, Any]:
    keys = ENTITY_KEYS if on_means == ON_MEANS_HEATING else (CONF_CLIMATE, CONF_INDOOR, CONF_OUTDOOR)
    options = {k: user_input[k] for k in keys if user_input.get(k) not in (None, "", [])}
    return {CONF_ON_MEANS: on_means, **options}


def _area_text(i: int, j: int) -> str:
    lat, lon = cell_centre(i, j)
    return f"{lat}, {lon}"


class HeatingConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1
    MINOR_VERSION = 2

    def __init__(self) -> None:
        self._on_means = ON_MEANS_SWITCHED_ON
        self._cell: tuple[int, int] = (0, 0)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        lat, lon = self.hass.config.latitude, self.hass.config.longitude
        if lat is None or lon is None or (lat == 0 and lon == 0):
            return self.async_abort(reason="no_location")
        self._cell = cell_for(lat, lon)

        if user_input is not None:
            self._on_means = user_input[CONF_ON_MEANS]
            return await self.async_step_entities()

        schema = vol.Schema(_on_means_field(ON_MEANS_SWITCHED_ON))
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            description_placeholders={"area": _area_text(*self._cell)},
        )

    async def async_step_entities(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_entities(self.hass, self._on_means, user_input)
            if not errors:
                cell_i, cell_j = self._cell
                api = HeatingApi(async_get_clientsession(self.hass), API_URL)
                try:
                    reg = await api.register(cell_i, cell_j)
                except ApiError:
                    errors["base"] = "cannot_connect"
                else:
                    await self.async_set_unique_id(reg["device_id"])
                    return self.async_create_entry(
                        title="Should I put the heating on?",
                        data={
                            CONF_TOKEN: reg["token"],
                            CONF_DEVICE_ID: reg["device_id"],
                            CONF_CELL_I: cell_i,
                            CONF_CELL_J: cell_j,
                        },
                        options=_entity_options(self._on_means, user_input),
                    )

        schema = vol.Schema(_entity_fields(self._on_means))
        return self.async_show_form(
            step_id="entities",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return HeatingOptionsFlow()


class HeatingOptionsFlow(OptionsFlow):
    """Change what counts as on, which entities are shared, or move the home to a new area."""

    def __init__(self) -> None:
        self._on_means = ON_MEANS_SWITCHED_ON

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self.config_entry
        if user_input is not None:
            if user_input.get(CONF_UPDATE_AREA):
                cell_i, cell_j = cell_for(self.hass.config.latitude, self.hass.config.longitude)
                self.hass.config_entries.async_update_entry(
                    entry, data={**entry.data, CONF_CELL_I: cell_i, CONF_CELL_J: cell_j}
                )
            self._on_means = user_input[CONF_ON_MEANS]
            return await self.async_step_entities()

        schema = vol.Schema({
            **_on_means_field(entry.options.get(CONF_ON_MEANS, ON_MEANS_SWITCHED_ON)),
            vol.Optional(CONF_UPDATE_AREA, default=False): BooleanSelector(),
        })
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            description_placeholders={"area": _area_text(entry.data[CONF_CELL_I], entry.data[CONF_CELL_J])},
        )

    async def async_step_entities(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_entities(self.hass, self._on_means, user_input)
            if not errors:
                return self.async_create_entry(data=_entity_options(self._on_means, user_input))

        schema = vol.Schema(_entity_fields(self._on_means))
        return self.async_show_form(
            step_id="entities",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or dict(self.config_entry.options)),
            errors=errors,
        )
