"""Diagnostic sensor: when this home last successfully reported."""
from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HeatingConfigEntry, device_info
from .const import signal_update


async def async_setup_entry(
    hass: HomeAssistant, entry: HeatingConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([LastReportSensor(entry)])


class LastReportSensor(SensorEntity):
    """The last time a report was accepted by the server."""

    _attr_has_entity_name = True
    _attr_name = "Last successful send"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(self, entry: HeatingConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_last_report"
        self._attr_device_info = device_info(entry)

    @property
    def native_value(self) -> datetime | None:
        return self._entry.runtime_data.last_report

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal_update(self._entry.entry_id), self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
