"""Share your heating status with shouldiputtheheatingon."""
from __future__ import annotations

from datetime import datetime
import logging
from statistics import mean

from homeassistant.components.climate import ATTR_CURRENT_TEMPERATURE, ATTR_HVAC_ACTION, HVACAction, HVACMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_TEMPERATURE,
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    Platform,
    UnitOfTemperature,
)
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import TemperatureConverter

from .api import ApiError, AuthError, HeatingApi, RateLimited
from .const import (
    API_URL,
    CONF_ACTIVE,
    CONF_ACTIVE_ABOVE,
    CONF_CELL_I,
    CONF_CELL_J,
    CONF_CLIMATE,
    CONF_INDOOR,
    CONF_ON_MEANS,
    CONF_OUTDOOR,
    CONF_TOKEN,
    CONF_URL,
    DOMAIN,
    MIN_SECONDS_BETWEEN_REPORTS,
    ON_MEANS_HEATING,
    ON_MEANS_SWITCHED_ON,
    REPORT_INTERVAL,
    signal_update,
)

_LOGGER = logging.getLogger(__name__)
# Thermostat modes that count as "switched on", whether or not it's firing right now.
HEATING_MODES = {HVACMode.HEAT, HVACMode.HEAT_COOL, HVACMode.AUTO}
# Thermostat actions that count as "actively heating".
HEATING_ACTIONS = {HVACAction.HEATING, HVACAction.PREHEATING}
# Text states a heating active sensor might report, e.g. the Wiser heat hub's "On"/"Off"
# or a Zigbee2MQTT thermostat's running state "heat"/"idle".
ACTIVE_TEXT_ON = {"on", "heat", "heating", "true", "running", "open"}
ACTIVE_TEXT_OFF = {"off", "idle", "false", "stopped", "closed"}
BAD_STATES = {STATE_UNKNOWN, STATE_UNAVAILABLE}
PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

type HeatingConfigEntry = ConfigEntry[Reporter]


def device_info(entry: HeatingConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="Should I put the heating on?",
        entry_type=DeviceEntryType.SERVICE,
    )


async def async_setup_entry(hass: HomeAssistant, entry: HeatingConfigEntry) -> bool:
    api = HeatingApi(async_get_clientsession(hass), API_URL, entry.data[CONF_TOKEN])
    reporter = Reporter(hass, entry, api)
    entry.runtime_data = reporter

    entry.async_on_unload(async_track_time_interval(hass, reporter.async_report, REPORT_INTERVAL))
    watched = [*entry.options.get(CONF_CLIMATE, []), *entry.options.get(CONF_ACTIVE, [])]
    entry.async_on_unload(async_track_state_change_event(hass, watched, reporter.async_state_changed))
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    entry.async_on_unload(reporter.cancel_pending)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_create_background_task(hass, reporter.async_report(), "shouldiputtheheatingon initial report")
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if entry.version > 1:
        return False
    if entry.minor_version < 2:
        # 1.2: several thermostats and active sensors, a choice of what "on" means,
        # and the website address is fixed rather than stored per home.
        # Homes that already had an active sensor were relying on it, so keep using it.
        options = dict(entry.options)
        for key in (CONF_CLIMATE, CONF_ACTIVE):
            if isinstance(options.get(key), str):
                options[key] = [options[key]]
        options[CONF_ON_MEANS] = ON_MEANS_HEATING if options.get(CONF_ACTIVE) else ON_MEANS_SWITCHED_ON
        data = {k: v for k, v in entry.data.items() if k != CONF_URL}
        hass.config_entries.async_update_entry(entry, data=data, options=options, minor_version=2)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HeatingConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Deleting the integration deletes this home from the website too."""
    api = HeatingApi(async_get_clientsession(hass), API_URL, entry.data[CONF_TOKEN])
    try:
        await api.delete_device()
    except ApiError as err:
        _LOGGER.warning("Couldn't remove this home from %s: %s", API_URL, err)


async def _async_update_listener(hass: HomeAssistant, entry: HeatingConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


class Reporter:
    """Reads the chosen entities and sends one reading to the server."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: HeatingApi) -> None:
        self.hass = hass
        self.entry = entry
        self.api = api
        self.last_report: datetime | None = None
        self.last_heating_on: bool | None = None
        self._auth_error_logged = False
        self._unknown_logged = False
        self._pending = None

    # ----- reading entities -----

    def _to_celsius(self, value: float, unit: str | None) -> float:
        if unit in (UnitOfTemperature.FAHRENHEIT, UnitOfTemperature.KELVIN):
            value = TemperatureConverter.convert(value, unit, UnitOfTemperature.CELSIUS)
        return round(value, 1)

    def _sensor_celsius(self, entity_id: str | None) -> float | None:
        if not entity_id or (state := self.hass.states.get(entity_id)) is None or state.state in BAD_STATES:
            return None
        try:
            value = float(state.state)
        except ValueError:
            return None
        return self._to_celsius(value, state.attributes.get(ATTR_UNIT_OF_MEASUREMENT))

    def _attr_celsius(self, value) -> float | None:
        if not isinstance(value, (int, float)):
            return None
        return self._to_celsius(float(value), self.hass.config.units.temperature_unit)

    def _climates(self) -> list:
        """The chosen thermostats that are currently reporting."""
        states = (self.hass.states.get(e) for e in self.entry.options[CONF_CLIMATE])
        return [s for s in states if s is not None and s.state not in BAD_STATES]

    def _active_reading(self, entity_id: str) -> bool | None:
        state = self.hass.states.get(entity_id)
        if state is None or state.state in BAD_STATES:
            return None
        value = state.state.strip().lower()
        if value in ACTIVE_TEXT_ON:
            return True
        if value in ACTIVE_TEXT_OFF:
            return False
        try:
            # A pump's power, a flow rate, a compressor's frequency...
            return float(value) > self.entry.options.get(CONF_ACTIVE_ABOVE, 0)
        except ValueError:
            return None

    def _heating_on(self, climates: list) -> bool | None:
        """Whether the heating counts as on, or None if the entities can't tell."""
        opts = self.entry.options
        if opts.get(CONF_ON_MEANS) == ON_MEANS_HEATING:
            if opts.get(CONF_ACTIVE):
                readings = [self._active_reading(e) for e in opts[CONF_ACTIVE]]
            else:
                readings = [
                    c.attributes[ATTR_HVAC_ACTION] in HEATING_ACTIONS
                    for c in climates
                    if c.attributes.get(ATTR_HVAC_ACTION) is not None
                ]
        else:
            # A thermostat in auto that says it's off (e.g. a summer mode) isn't switched on.
            readings = [
                c.state in HEATING_MODES and c.attributes.get(ATTR_HVAC_ACTION) != HVACAction.OFF
                for c in climates
            ]
        if any(readings):
            return True
        return False if any(r is not None for r in readings) else None

    def build_payload(self) -> dict | None:
        opts = self.entry.options
        climates = self._climates()
        if not climates or (heating_on := self._heating_on(climates)) is None:
            return None

        # With several thermostats, share the highest target and the average room temperature.
        targets = [self._attr_celsius(c.attributes.get(ATTR_TEMPERATURE)) for c in climates]
        target = max((t for t in targets if t is not None), default=None)
        if opts.get(CONF_INDOOR):
            indoor = self._sensor_celsius(opts[CONF_INDOOR])
        else:
            rooms = [self._attr_celsius(c.attributes.get(ATTR_CURRENT_TEMPERATURE)) for c in climates]
            rooms = [t for t in rooms if t is not None]
            indoor = round(mean(rooms), 1) if rooms else None
        outdoor = self._sensor_celsius(opts.get(CONF_OUTDOOR))
        if outdoor is None:
            _LOGGER.debug("Outdoor sensor %s has no usable reading", opts.get(CONF_OUTDOOR))

        # Drop values the server would reject (e.g. Hive reports 1 °C when off).
        if target is not None and not 5 <= target <= 35:
            target = None
        if indoor is not None and not -10 <= indoor <= 45:
            indoor = None
        if outdoor is not None and not -50 <= outdoor <= 55:
            outdoor = None

        return {
            "heating_on": heating_on,
            "target_temp": target,
            "indoor_temp": indoor,
            "outdoor_temp": outdoor,
            "cell": {"i": self.entry.data[CONF_CELL_I], "j": self.entry.data[CONF_CELL_J]},
        }

    # ----- sending -----

    async def async_report(self, _now: datetime | None = None) -> None:
        payload = self.build_payload()
        if payload is None:
            if not self._unknown_logged:
                opts = self.entry.options
                _LOGGER.warning(
                    "Can't tell whether the heating is on from %s",
                    ", ".join([*opts[CONF_CLIMATE], *opts.get(CONF_ACTIVE, [])]),
                )
                self._unknown_logged = True
            # Don't keep showing a stale reading as if it were current.
            if self.last_heating_on is not None:
                self.last_heating_on = None
                async_dispatcher_send(self.hass, signal_update(self.entry.entry_id))
            return
        self._unknown_logged = False
        try:
            await self.api.report(payload)
        except AuthError:
            if not self._auth_error_logged:
                _LOGGER.error(
                    "The server no longer recognises this home. Delete and re-add the "
                    "Should I put the heating on? integration to start sharing again"
                )
                self._auth_error_logged = True
            return
        except RateLimited:
            return
        except ApiError as err:
            _LOGGER.warning("Couldn't send heating status: %s", err)
            return
        self._auth_error_logged = False
        self.last_report = dt_util.utcnow()
        self.last_heating_on = payload["heating_on"]
        async_dispatcher_send(self.hass, signal_update(self.entry.entry_id))

    @callback
    def async_state_changed(self, event: Event[EventStateChangedData]) -> None:
        """Report promptly when the heating switches on or off, not just every 5 minutes."""
        heating_on = self._heating_on(self._climates())
        if heating_on is None or heating_on == self.last_heating_on:
            return
        if self._pending:
            return
        wait = 0.0
        if self.last_report:
            elapsed = (dt_util.utcnow() - self.last_report).total_seconds()
            wait = max(0.0, MIN_SECONDS_BETWEEN_REPORTS - elapsed)
        self._pending = async_call_later(self.hass, wait, self._async_fire_pending)

    async def _async_fire_pending(self, _now: datetime) -> None:
        self._pending = None
        await self.async_report()

    @callback
    def cancel_pending(self) -> None:
        if self._pending:
            self._pending()
            self._pending = None
