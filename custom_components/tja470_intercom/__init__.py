"""The Hager TJA470 Intercom integration."""
from __future__ import annotations

from datetime import timedelta
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from aiotja470_intercom import TJA470IntercomClient, AiohttpRunner
from aiotja470_intercom.exceptions import TJA470AuthError, TJA470Error

from .const import CONF_COOKIES, CONF_UUID, DOMAIN, LOGGER

PLATFORMS = [Platform.CAMERA, Platform.BUTTON, Platform.SENSOR]

SERVICE_OPEN_DOOR = "open_door"
SERVICE_OPEN_DOOR_AT_POSITION = "open_door_at_position"
SERVICE_SWITCH_CAMERA = "switch_camera"
SERVICE_GET_SIP_CREDENTIALS = "get_sip_credentials"


class TJA470Coordinator(DataUpdateCoordinator[dict]):
    """Coordinator for TJA470 data updates."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: TJA470IntercomClient,
        entry: ConfigEntry,
    ) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=30),
        )
        self.client = client
        self.entry = entry

    async def _async_update_data(self) -> dict:
        """Fetch data from TJA470 Intercom."""
        uuid_str = self.entry.data[CONF_UUID]
        try:
            provisioning_info = await self.client.get_provisioning(uuid_str)
            manifest = await self.client.get_manifest()

            # Dynamic cookie management: persist cookies if they changed
            updated_cookies = self.client.get_cookies()
            if updated_cookies != self.entry.data.get(CONF_COOKIES):
                LOGGER.debug("Saving updated cookies to config entry")
                new_data = {**self.entry.data, CONF_COOKIES: updated_cookies}
                self.hass.config_entries.async_update_entry(self.entry, data=new_data)

            return {
                "provisioning": provisioning_info,
                "manifest": manifest,
            }
        except TJA470AuthError as err:
            raise ConfigEntryAuthFailed("Authentication failed") from err
        except TJA470Error as err:
            raise UpdateFailed(f"Error communicating with TJA470: {err}") from err


async def async_register_lovelace_resource(hass: HomeAssistant) -> None:
    """Register Lovelace resource dynamically."""
    import os
    www_dir = os.path.join(os.path.dirname(__file__), "www")

    # Serve static path for the card
    if hasattr(hass, "http"):
        from homeassistant.components.http import StaticPathConfig
        await hass.http.async_register_static_paths([
            StaticPathConfig(
                "/tja470-intercom",
                www_dir,
                False,
            )
        ])

    async def async_register(event=None) -> None:
        """Register Lovelace resource in the frontend registry."""
        if "lovelace" not in hass.data:
            LOGGER.debug("Lovelace not in hass.data, skipping resource registration")
            return

        lovelace = hass.data["lovelace"]
        if not hasattr(lovelace, "resources") or getattr(lovelace, "resource_mode", None) != "storage":
            LOGGER.debug("Lovelace is in YAML mode or resources not accessible, skipping resource registration")
            return

        resources = lovelace.resources
        if not resources.loaded:
            await resources.async_load()

        url = "/tja470-intercom/tja470-intercom-card.js?v=1.0.0"

        # Check if already registered
        for item in resources.async_items():
            if item.get("url", "").startswith("/tja470-intercom/tja470-intercom-card.js"):
                if item.get("url") != url:
                    LOGGER.debug("Updating Lovelace resource version to %s", url)
                    await resources.async_update_item(
                        item["id"],
                        {"res_type": "module", "url": url}
                    )
                return

        # Not registered yet, create it
        LOGGER.debug("Registering Lovelace resource: %s", url)
        await resources.async_create_item({
            "res_type": "module",
            "url": url,
        })

    if hass.is_running:
        await async_register()
    else:
        from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, async_register)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Hager TJA470 Intercom from a config entry."""
    # Register Lovelace custom card resource dynamically
    await async_register_lovelace_resource(hass)

    host = entry.data[CONF_HOST]
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    cookies = entry.data.get(CONF_COOKIES)

    session = async_get_clientsession(hass)
    runner = AiohttpRunner(session)
    client = TJA470IntercomClient(host, username, password, runner)
    if cookies:
        client.set_cookies(cookies)

    coordinator = TJA470Coordinator(hass, client, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
    }

    # Register devices
    device_registry = dr.async_get(hass)
    # Controller device
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=f"TJA470 Intercom Controller ({host})",
        manufacturer="Hager",
        model="TJA470",
        sw_version=coordinator.data["manifest"].fw,
    )

    # Door station devices
    prov = coordinator.data["provisioning"]
    for element in prov.called_elements:
        if element.order is not None:
            device_registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={(DOMAIN, f"door_{element.sip_id}")},
                name=element.name or f"Door Station {element.order}",
                manufacturer="Hager",
                model="TJA470 Door Station",
                via_device=(DOMAIN, entry.entry_id),
            )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register custom services
    async def async_resolve_clients(device_ids: list[str]) -> list[TJA470IntercomClient]:
        """Resolve device IDs to intercom clients."""
        clients: list[TJA470IntercomClient] = []
        if not device_ids:
            # Fallback to all loaded entries
            for val in hass.data[DOMAIN].values():
                clients.append(val["client"])
            return clients

        device_reg = dr.async_get(hass)
        for dev_id in device_ids:
            device = device_reg.async_get(dev_id)
            if not device:
                continue
            for entry_id in device.config_entries:
                if entry_id in hass.data[DOMAIN]:
                    clients.append(hass.data[DOMAIN][entry_id]["client"])
        return list(set(clients))

    async def handle_open_door(call: ServiceCall) -> None:
        """Service handler to open active door."""
        device_ids = call.data.get("device_id", [])
        door_id = call.data.get("door_id", 1)
        clients = await async_resolve_clients(device_ids)
        if not clients:
            raise HomeAssistantError("No TJA470 integration clients found")

        for cli in clients:
            try:
                await cli.open_door(door_id=door_id)
            except TJA470Error as err:
                raise HomeAssistantError(f"Failed to open door: {err}") from err

    async def handle_open_door_at_position(call: ServiceCall) -> None:
        """Service handler to switch camera and open door."""
        device_ids = call.data.get("device_id", [])
        position = call.data["position"]
        door_id = call.data.get("door_id", 1)
        max_attempts = call.data.get("max_attempts", 10)
        clients = await async_resolve_clients(device_ids)
        if not clients:
            raise HomeAssistantError("No TJA470 integration clients found")

        for cli in clients:
            # We need the client uuid associated with this entry
            # Let's find which entry matches the client
            client_uuid = None
            for val in hass.data[DOMAIN].values():
                if val["client"] == cli:
                    client_uuid = val["coordinator"].entry.data[CONF_UUID]
                    break
            if not client_uuid:
                continue
            try:
                await cli.open_door_at_position(
                    client_uuid, position, door_id=door_id, max_attempts=max_attempts
                )
            except TJA470Error as err:
                raise HomeAssistantError(
                    f"Failed to open door at position {position}: {err}"
                ) from err

    async def handle_switch_camera(call: ServiceCall) -> None:
        """Service handler to switch active camera."""
        device_ids = call.data.get("device_id", [])
        position = call.data.get("position")
        max_attempts = call.data.get("max_attempts", 10)
        clients = await async_resolve_clients(device_ids)
        if not clients:
            raise HomeAssistantError("No TJA470 integration clients found")

        for cli in clients:
            client_uuid = None
            for val in hass.data[DOMAIN].values():
                if val["client"] == cli:
                    client_uuid = val["coordinator"].entry.data[CONF_UUID]
                    break
            if not client_uuid:
                continue
            try:
                if position is not None:
                    await cli.switch_to_camera_position(
                        client_uuid, position, max_attempts=max_attempts
                    )
                else:
                    await cli.switch_camera(client_uuid)
            except TJA470Error as err:
                raise HomeAssistantError(f"Failed to switch camera: {err}") from err

    async def handle_get_sip_credentials(call: ServiceCall) -> ServiceResponse:
        """Service handler to get SIP credentials."""
        device_ids = call.data.get("device_id", [])
        clients = await async_resolve_clients(device_ids)
        if not clients:
            raise HomeAssistantError("No TJA470 integration clients found")

        client = clients[0]
        coordinator = None
        for val in hass.data[DOMAIN].values():
            if val["client"] == client:
                coordinator = val["coordinator"]
                break
        if not coordinator or not coordinator.data or "provisioning" not in coordinator.data:
            raise HomeAssistantError("Provisioning data not loaded yet")

        prov = coordinator.data["provisioning"]
        sip_info = prov.sip_info
        return {
            "sip_registrar": coordinator.entry.data[CONF_HOST],
            "sip_username": sip_info.sip_id,
            "sip_password": sip_info.sip_password,
        }

    # Register services if they are not already registered
    if not hass.services.has_service(DOMAIN, SERVICE_OPEN_DOOR):
        hass.services.async_register(
            DOMAIN,
            SERVICE_OPEN_DOOR,
            handle_open_door,
            schema=vol.Schema(
                {
                    vol.Optional("device_id"): vol.All(cv.ensure_list, [cv.string]),
                    vol.Optional("door_id", default=1): cv.positive_int,
                }
            ),
        )

    if not hass.services.has_service(DOMAIN, SERVICE_OPEN_DOOR_AT_POSITION):
        hass.services.async_register(
            DOMAIN,
            SERVICE_OPEN_DOOR_AT_POSITION,
            handle_open_door_at_position,
            schema=vol.Schema(
                {
                    vol.Optional("device_id"): vol.All(cv.ensure_list, [cv.string]),
                    vol.Required("position"): cv.positive_int,
                    vol.Optional("door_id", default=1): cv.positive_int,
                    vol.Optional("max_attempts", default=10): cv.positive_int,
                }
            ),
        )

    if not hass.services.has_service(DOMAIN, SERVICE_SWITCH_CAMERA):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SWITCH_CAMERA,
            handle_switch_camera,
            schema=vol.Schema(
                {
                    vol.Optional("device_id"): vol.All(cv.ensure_list, [cv.string]),
                    vol.Optional("position"): cv.positive_int,
                    vol.Optional("max_attempts", default=10): cv.positive_int,
                }
            ),
        )

    if not hass.services.has_service(DOMAIN, SERVICE_GET_SIP_CREDENTIALS):
        hass.services.async_register(
            DOMAIN,
            SERVICE_GET_SIP_CREDENTIALS,
            handle_get_sip_credentials,
            schema=vol.Schema(
                {
                    vol.Optional("device_id"): vol.All(cv.ensure_list, [cv.string]),
                }
            ),
            supports_response=SupportsResponse.ONLY,
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

        # If no config entries left, remove services
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_OPEN_DOOR)
            hass.services.async_remove(DOMAIN, SERVICE_OPEN_DOOR_AT_POSITION)
            hass.services.async_remove(DOMAIN, SERVICE_SWITCH_CAMERA)
            hass.services.async_remove(DOMAIN, SERVICE_GET_SIP_CREDENTIALS)

    return unload_ok
