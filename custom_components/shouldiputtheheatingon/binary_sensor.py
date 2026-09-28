"""Binary sensor: the heating status last reported to the server."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HeatingConfigEntry, device_info
from .const import signal_update


async def async_setup_entry(
    hass: HomeAssistant, entry: HeatingConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([HeatingStatusSensor(entry)])


class HeatingStatusSensor(BinarySensorEntity):
    """Whether the last report sent to the server said the heating was on."""

    _attr_has_entity_name = True
    _attr_name = "Heating status reported"
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_icon = "mdi:radiator"
    _attr_should_poll = False

    def __init__(self, entry: HeatingConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_heating_status"
        self._attr_device_info = device_info(entry)

    @property
    def is_on(self) -> bool | None:
        return self._entry.runtime_data.last_heating_on

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal_update(self._entry.entry_id), self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
