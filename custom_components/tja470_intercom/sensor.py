"""Sensor platform for Hager TJA470 Intercom."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import TJA470Coordinator

PARALLEL_UPDATES = 0


def get_call_state_name(entry: ConfigEntry) -> str:
    """Return the state name of the active call."""
    try:
        active_call = entry.runtime_data.active_call
    except AttributeError:
        active_call = None
    if active_call:
        from pyVoIP.VoIP import CallState
        if active_call.state == CallState.ANSWERED:
            return "answered"
        if active_call.state in (CallState.RINGING, CallState.DIALING):
            if getattr(active_call, "is_outgoing", False):
                return "dialing"
            return "ringing"
    return "idle"


def get_caller(entry: ConfigEntry) -> str | None:
    """Return the caller ID of the active call."""
    try:
        active_call = entry.runtime_data.active_call
    except AttributeError:
        active_call = None
    if active_call:
        if getattr(active_call, "is_outgoing", False):
            val = getattr(active_call, "dest_number", active_call.caller)
            return str(val) if val is not None else None
        return str(active_call.caller) if active_call.caller is not None else None
    return None


@dataclass(frozen=True, kw_only=True)
class TJA470SensorEntityDescription(SensorEntityDescription):
    """Class describing TJA470 sensor entities."""

    value_fn: Callable[[dict[str, Any], ConfigEntry], str | None]


SENSOR_DESCRIPTIONS: tuple[TJA470SensorEntityDescription, ...] = (
    TJA470SensorEntityDescription(
        key="sip_registrar",
        translation_key="sip_registrar",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data, entry: entry.data[CONF_HOST],
    ),
    TJA470SensorEntityDescription(
        key="rtsp_url",
        translation_key="rtsp_url",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data, entry: data["provisioning"].rtsp_video_url.replace(
            "${ipadress}", entry.data[CONF_HOST]
        )
        if data["provisioning"].rtsp_video_url
        else None,
    ),
    TJA470SensorEntityDescription(
        key="sip_status",
        translation_key="sip_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data, entry: data.get("sip_status", "INACTIVE"),
    ),
    TJA470SensorEntityDescription(
        key="call_state",
        translation_key="call_state",
        value_fn=lambda data, entry: get_call_state_name(entry),
    ),
    TJA470SensorEntityDescription(
        key="caller",
        translation_key="caller",
        value_fn=lambda data, entry: get_caller(entry),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform for TJA470."""
    coordinator: TJA470Coordinator = entry.runtime_data.coordinator

    async_add_entities(
        TJA470Sensor(coordinator, description) for description in SENSOR_DESCRIPTIONS
    )


class TJA470Sensor(CoordinatorEntity[TJA470Coordinator], SensorEntity):
    """Sensor entity representing TJA470 diagnostics."""

    entity_description: TJA470SensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TJA470Coordinator,
        description: TJA470SensorEntityDescription,
    ) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
        )

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        await super().async_added_to_hass()
        if self.entity_description.key in ("call_state", "caller"):
            from homeassistant.helpers.dispatcher import async_dispatcher_connect
            self.async_on_remove(
                async_dispatcher_connect(
                    self.hass,
                    f"{DOMAIN}_{self.coordinator.entry.entry_id}_call_update",
                    self.async_write_ha_state,
                )
            )

    @property
    def native_value(self) -> str | None:
        """Return the native value of the sensor."""
        return self.entity_description.value_fn(self.coordinator.data, self.coordinator.entry)
