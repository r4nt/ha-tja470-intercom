"""Button platform for Hager TJA470 Intercom."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from aiotja470_intercom import TJA470IntercomClient
from aiotja470_intercom.models import CalledElement

from .const import CONF_UUID, DOMAIN
from .coordinator import TJA470Coordinator

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the button platform for TJA470."""
    client: TJA470IntercomClient = entry.runtime_data.client
    coordinator: TJA470Coordinator = entry.runtime_data.coordinator

    prov = coordinator.data["provisioning"]
    known_sip_ids: set[str] = set()

    entities: list[ButtonEntity] = [
        TJA470OpenActiveDoorButton(coordinator, client),
        TJA470SwitchCameraButton(coordinator, client),
    ]
    for element in prov.called_elements:
        if element.order is not None:
            known_sip_ids.add(element.sip_id)
            entities.append(TJA470OpenDoorButton(coordinator, client, element))

    async_add_entities(entities)

    @callback
    def _async_add_new_door_buttons() -> None:
        """Add button entities for door stations that appear after initial setup."""
        new_prov = coordinator.data.get("provisioning") if coordinator.data else None
        if new_prov is None:
            return
        new_entities = []
        for element in new_prov.called_elements:
            if element.order is not None and element.sip_id not in known_sip_ids:
                known_sip_ids.add(element.sip_id)
                device_reg = dr.async_get(hass)
                device_reg.async_get_or_create(
                    config_entry_id=entry.entry_id,
                    identifiers={(DOMAIN, f"door_{element.sip_id}")},
                    name=element.name or f"Door Station {element.order}",
                    manufacturer="Hager",
                    model="TJA470 Door Station",
                    via_device=(DOMAIN, entry.entry_id),
                )
                new_entities.append(TJA470OpenDoorButton(coordinator, client, element))
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_door_buttons))


class TJA470OpenActiveDoorButton(CoordinatorEntity[TJA470Coordinator], ButtonEntity):
    """Button to open the currently active door."""

    _attr_has_entity_name = True
    _attr_translation_key = "open_active_door"

    def __init__(
        self,
        coordinator: TJA470Coordinator,
        client: TJA470IntercomClient,
    ) -> None:
        """Initialize button."""
        super().__init__(coordinator)
        self.client = client
        self._attr_unique_id = f"{coordinator.entry.entry_id}_open_active_door"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
        )

    async def async_press(self) -> None:
        """Press the button."""
        await self.client.open_door(door_id=1)


class TJA470SwitchCameraButton(CoordinatorEntity[TJA470Coordinator], ButtonEntity):
    """Button to switch the active camera feed to the next position."""

    _attr_has_entity_name = True
    _attr_translation_key = "switch_camera"

    def __init__(
        self,
        coordinator: TJA470Coordinator,
        client: TJA470IntercomClient,
    ) -> None:
        """Initialize button."""
        super().__init__(coordinator)
        self.client = client
        self._attr_unique_id = f"{coordinator.entry.entry_id}_switch_camera"
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
    _attr_translation_key = "open_door"

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
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"door_{element.sip_id}")},
        )

    async def async_press(self) -> None:
        """Press the button."""
        uuid_str = self.coordinator.entry.data[CONF_UUID]
        await self.client.open_door_at_position(
            uuid_str, self.element.order, door_id=1
        )
