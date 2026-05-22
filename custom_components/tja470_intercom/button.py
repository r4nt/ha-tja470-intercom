"""Button platform for Hager TJA470 Intercom."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from aiotja470_intercom import TJA470IntercomClient
from aiotja470_intercom.models import CalledElement

from .const import CONF_UUID, DOMAIN
from . import TJA470Coordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the button platform for TJA470."""
    data = hass.data[DOMAIN][entry.entry_id]
    client: TJA470IntercomClient = data["client"]
    coordinator: TJA470Coordinator = data["coordinator"]

    entities: list[ButtonEntity] = []

    # Add active door release button for the controller
    entities.append(TJA470OpenActiveDoorButton(coordinator, client))
    # Add switch camera button for the controller
    entities.append(TJA470SwitchCameraButton(coordinator, client))

    # Add individual door release buttons for each door station element
    prov = coordinator.data["provisioning"]
    for element in prov.called_elements:
        if element.order is not None:
            entities.append(TJA470OpenDoorButton(coordinator, client, element))

    async_add_entities(entities)


class TJA470OpenActiveDoorButton(CoordinatorEntity[TJA470Coordinator], ButtonEntity):
    """Button to open the currently active door."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:door-open"

    def __init__(
        self,
        coordinator: TJA470Coordinator,
        client: TJA470IntercomClient,
    ) -> None:
        """Initialize button."""
        super().__init__(coordinator)
        self.client = client
        self._attr_unique_id = f"{coordinator.entry.entry_id}_open_active_door"
        self._attr_name = "Open Active Door"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
        )

    async def async_press(self) -> None:
        """Press the button."""
        await self.client.open_door(door_id=1)


class TJA470SwitchCameraButton(CoordinatorEntity[TJA470Coordinator], ButtonEntity):
    """Button to switch the active camera feed to the next position."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:camera-switch"

    def __init__(
        self,
        coordinator: TJA470Coordinator,
        client: TJA470IntercomClient,
    ) -> None:
        """Initialize button."""
        super().__init__(coordinator)
        self.client = client
        self._attr_unique_id = f"{coordinator.entry.entry_id}_switch_camera"
        self._attr_name = "Switch Camera"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
        )

    async def async_press(self) -> None:
        """Press the button."""
        uuid_str = self.coordinator.entry.data[CONF_UUID]
        await self.client.switch_camera(uuid_str)
        await self.coordinator.async_request_refresh()


class TJA470OpenDoorButton(CoordinatorEntity[TJA470Coordinator], ButtonEntity):
    """Button to open a specific door station."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:door-open"

    def __init__(
        self,
        coordinator: TJA470Coordinator,
        client: TJA470IntercomClient,
        element: CalledElement,
    ) -> None:
        """Initialize button."""
        super().__init__(coordinator)
        self.client = client
        self.element = element
        self._attr_unique_id = f"{coordinator.entry.entry_id}_open_door_{element.sip_id}"
        self._attr_name = "Open"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"door_{element.sip_id}")},
        )

    async def async_press(self) -> None:
        """Press the button."""
        uuid_str = self.coordinator.entry.data[CONF_UUID]
        await self.client.open_door_at_position(
            uuid_str, self.element.order, door_id=1
        )
