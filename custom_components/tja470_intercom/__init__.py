"""The Hager TJA470 Intercom integration."""
from __future__ import annotations

import asyncio
from datetime import timedelta
import voluptuous as vol
from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from pyVoIP.VoIP import CallState

from aiotja470_intercom import TJA470IntercomClient, AiohttpRunner, TJA470SipPhone, TJA470SipCall
from aiotja470_intercom.exceptions import TJA470AuthError, TJA470Error

from .const import CONF_COOKIES, CONF_UUID, DOMAIN, LOGGER

PLATFORMS = [Platform.CAMERA, Platform.BUTTON, Platform.SENSOR]

SERVICE_OPEN_DOOR = "open_door"
SERVICE_OPEN_DOOR_AT_POSITION = "open_door_at_position"
SERVICE_SWITCH_CAMERA = "switch_camera"
SERVICE_GET_SIP_CREDENTIALS = "get_sip_credentials"
SERVICE_ANSWER_CALL = "answer_call"
SERVICE_HANGUP_CALL = "hangup_call"
SERVICE_INITIATE_CALL = "initiate_call"
SERVICE_TRIGGER_INCOMING_RING = "trigger_incoming_ring"


class TJA470AudioStreamView(HomeAssistantView):
    """Websocket view for audio streaming."""
    url = "/api/tja470_intercom/audio_stream"
    name = "api:tja470_intercom:audio_stream"
    requires_auth = False

    async def get(self, request: web.Request) -> web.WebSocketResponse:
        """Handle websocket connection."""
        hass = request.app["hass"]
        entry_id = request.query.get("entry_id")
        token = request.query.get("token")

        if not token:
            return web.Response(status=401, text="Unauthorized")

        refresh_token = hass.auth.async_validate_access_token(token)
        if refresh_token is None:
            return web.Response(status=401, text="Unauthorized")

        if not entry_id or entry_id not in hass.data[DOMAIN]:
            return web.Response(status=400, text="Invalid entry_id")

        entry_data = hass.data[DOMAIN][entry_id]
        active_call = entry_data.get("active_call")
        if not active_call:
            return web.Response(status=400, text="No active call")

        ws = web.WebSocketResponse()
        await ws.prepare(request)

        LOGGER.info("Websocket audio stream connected for call: %s", active_call)

        async def send_audio():
            try:
                # Wait until call is answered
                while active_call.state in (CallState.RINGING, CallState.DIALING):
                    if ws.closed or active_call.state == CallState.ENDED:
                        break
                    await asyncio.sleep(0.1)

                async for frame in active_call.audio_stream(convert_16bit=True):
                    if ws.closed:
                        break
                    await ws.send_bytes(frame)
            except Exception as e:
                LOGGER.error("Error sending audio to websocket: %s", e)

        async def receive_audio():
            try:
                async for msg in ws:
                    if msg.type == web.WSMsgType.BINARY:
                        await active_call.write_audio_16bit(msg.data)
                    elif msg.type in (web.WSMsgType.CLOSE, web.WSMsgType.CLOSING, web.WSMsgType.CLOSED):
                        break
            except Exception as e:
                LOGGER.error("Error receiving audio from websocket: %s", e)

        # Run send and receive concurrently
        await asyncio.gather(send_audio(), receive_audio())
        LOGGER.info("Websocket audio stream disconnected")
        return ws


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

            sip_phone = None
            if self.entry.entry_id in self.hass.data.get(DOMAIN, {}):
                sip_phone = self.hass.data[DOMAIN][self.entry.entry_id].get("sip_phone")
            sip_status = sip_phone.get_status().name if sip_phone else "INACTIVE"

            return {
                "provisioning": provisioning_info,
                "manifest": manifest,
                "sip_status": sip_status,
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

        url = "/tja470-intercom/tja470-intercom-card.js?v=1.0.9"

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


async def async_register_custom_panel(hass: HomeAssistant) -> None:
    """Register custom sidebar panel dynamically."""
    # Check if already registered
    url_path = "intercom"
    if url_path in hass.data.get("frontend_panels", {}):
        LOGGER.debug("Custom panel %s already registered", url_path)
        return

    LOGGER.debug("Registering custom panel: %s", url_path)
    from homeassistant.components import panel_custom
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=url_path,
        webcomponent_name="tja470-intercom-panel",
        sidebar_title="Intercom",
        sidebar_icon="mdi:phone-in-talk",
        module_url="/tja470-intercom/tja470-intercom-panel.js?v=1.0.9",
        require_admin=False,
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Hager TJA470 Intercom from a config entry."""
    # Register Lovelace custom card resource dynamically
    await async_register_lovelace_resource(hass)
    # Register custom sidebar panel dynamically
    await async_register_custom_panel(hass)

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

    # Get local source IP address for SIP phone
    from homeassistant.components.network import async_get_source_ip
    local_ip = await async_get_source_ip(hass, host)

    # Initialize SIP phone client
    prov = coordinator.data["provisioning"]
    sip_info = prov.sip_info
    
    sip_phone = TJA470SipPhone(
        host=host,
        sip_id=sip_info.sip_id,
        sip_password=sip_info.sip_password,
        local_ip=local_ip,
    )

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
        "sip_phone": sip_phone,
        "active_call": None,
    }

    # Register callbacks on SIP phone
    async def handle_incoming_call(call: TJA470SipCall) -> None:
        LOGGER.info("Incoming SIP call from %s", call.caller)
        call.is_outgoing = False
        hass.data[DOMAIN][entry.entry_id]["active_call"] = call
        from homeassistant.helpers.dispatcher import async_dispatcher_send
        async_dispatcher_send(hass, f"{DOMAIN}_{entry.entry_id}_call_update")

        # Send notifications if configured
        async def send_notifications() -> None:
            options = entry.options
            notify_devices = options.get("notify_devices", [])

            if not notify_devices:
                return

            caller_name = call.caller
            if coordinator and coordinator.data and "provisioning" in coordinator.data:
                prov = coordinator.data["provisioning"]
                for element in prov.called_elements:
                    if element.sip_id == call.caller:
                        if element.name:
                            caller_name = element.name
                        break

            for device in notify_devices:
                # Normalize full entity ID if user supplied it with/without notify. prefix
                entity_id = device if device.startswith("notify.") else f"notify.{device}"

                LOGGER.debug("Sending incoming call notification to %s", entity_id)
                try:
                    # Check if the device is registered as a modern notify entity in HA
                    if hass.states.get(entity_id) is not None:
                        LOGGER.debug("Using modern send_message service for notify entity: %s", entity_id)
                        await hass.services.async_call(
                            "notify",
                            "send_message",
                            {
                                "message": f"Incoming call from {caller_name}",
                                "title": "Intercom Call",
                                "data": {
                                    "ttl": 0,
                                    "priority": "high",
                                    "channel": "intercom",
                                    "clickAction": "/intercom",
                                },
                            },
                            target={"entity_id": entity_id},
                        )
                    else:
                        # Fallback to legacy notify service call
                        service_name = entity_id.split(".", 1)[1]
                        LOGGER.debug("Using legacy service notify.%s", service_name)
                        await hass.services.async_call(
                            "notify",
                            service_name,
                            {
                                "title": "Intercom Call",
                                "message": f"Incoming call from {caller_name}",
                                "data": {
                                    "ttl": 0,
                                    "priority": "high",
                                    "channel": "intercom",
                                    "clickAction": "/intercom",
                                },
                            },
                        )
                except Exception as err:
                    LOGGER.error("Failed to send notification to %s: %s", entity_id, err)

        hass.async_create_task(send_notifications())

        async def monitor_call() -> None:
            while call.state not in (CallState.ENDED, None):
                await asyncio.sleep(0.5)
            LOGGER.info("SIP call ended: %s", call)
            if hass.data[DOMAIN][entry.entry_id].get("active_call") == call:
                hass.data[DOMAIN][entry.entry_id]["active_call"] = None
            async_dispatcher_send(hass, f"{DOMAIN}_{entry.entry_id}_call_update")

        hass.async_create_task(monitor_call())

    async def handle_registration_state(state) -> None:
        LOGGER.info("SIP registration state changed: %s", state)
        from homeassistant.helpers.dispatcher import async_dispatcher_send
        async_dispatcher_send(hass, f"{DOMAIN}_{entry.entry_id}_call_update")

    sip_phone.register_incoming_call_callback(handle_incoming_call)
    sip_phone.register_registration_state_callback(handle_registration_state)

    try:
        await sip_phone.start()
    except Exception as err:
        LOGGER.error("Failed to start SIP phone: %s", err)

    # Register the websocket view once
    if "websocket_view_registered" not in hass.data[DOMAIN]:
        hass.http.register_view(TJA470AudioStreamView())
        hass.data[DOMAIN]["websocket_view_registered"] = True

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
    async def async_resolve_entry_ids(call_data: dict) -> list[str]:
        """Resolve device_id or entity_id to config entry IDs."""
        device_ids = call_data.get("device_id", [])
        entity_ids = call_data.get("entity_id", [])
        entry_ids = []

        if entity_ids:
            from homeassistant.helpers import entity_registry as er
            ent_reg = er.async_get(hass)
            for ent_id in entity_ids:
                ent = ent_reg.async_get(ent_id)
                if ent and ent.config_entry_id:
                    entry_ids.append(ent.config_entry_id)

        if device_ids:
            device_reg = dr.async_get(hass)
            for dev_id in device_ids:
                device = device_reg.async_get(dev_id)
                if device:
                    entry_ids.extend(device.config_entries)

        if not entry_ids:
            entry_ids = [k for k in hass.data[DOMAIN].keys() if k != "websocket_view_registered"]

        return list(set(entry_ids))

    async def async_resolve_clients(device_ids: list[str]) -> list[TJA470IntercomClient]:
        """Resolve device IDs to intercom clients."""
        clients: list[TJA470IntercomClient] = []
        entry_ids = await async_resolve_entry_ids({"device_id": device_ids})
        for entry_id in entry_ids:
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
            client_uuid = None
            for val in hass.data[DOMAIN].values():
                if isinstance(val, dict) and val.get("client") == cli:
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
                if isinstance(val, dict) and val.get("client") == cli:
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
            if isinstance(val, dict) and val.get("client") == client:
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

    async def handle_answer_call(call: ServiceCall) -> None:
        """Service handler to answer the active call."""
        entry_ids = await async_resolve_entry_ids(call.data)
        for entry_id in entry_ids:
            if entry_id in hass.data[DOMAIN]:
                active_call = hass.data[DOMAIN][entry_id].get("active_call")
                if active_call:
                    try:
                        await active_call.answer()
                    except Exception as err:
                        raise HomeAssistantError(f"Failed to answer call: {err}") from err
                    finally:
                        from homeassistant.helpers.dispatcher import async_dispatcher_send
                        async_dispatcher_send(hass, f"{DOMAIN}_{entry_id}_call_update")

    async def handle_hangup_call(call: ServiceCall) -> None:
        """Service handler to hang up the active call."""
        entry_ids = await async_resolve_entry_ids(call.data)
        for entry_id in entry_ids:
            if entry_id in hass.data[DOMAIN]:
                active_call = hass.data[DOMAIN][entry_id].get("active_call")
                if active_call:
                    try:
                        await active_call.hangup()
                    except Exception as err:
                        raise HomeAssistantError(f"Failed to hang up call: {err}") from err
                    finally:
                        hass.data[DOMAIN][entry_id]["active_call"] = None
                        from homeassistant.helpers.dispatcher import async_dispatcher_send
                        async_dispatcher_send(hass, f"{DOMAIN}_{entry_id}_call_update")

    async def handle_initiate_call(call: ServiceCall) -> None:
        """Service handler to initiate an outgoing call."""
        number = call.data["number"]
        entry_ids = await async_resolve_entry_ids(call.data)
        for entry_id in entry_ids:
            if entry_id in hass.data[DOMAIN]:
                sip_phone = hass.data[DOMAIN][entry_id].get("sip_phone")
                if sip_phone:
                    # Hang up any existing active call first
                    old_call = hass.data[DOMAIN][entry_id].get("active_call")
                    if old_call:
                        try:
                            await old_call.hangup()
                        except Exception as e:
                            LOGGER.debug("Failed to hang up previous call before initiating new call: %s", e)

                    class PlaceholderCall:
                        def __init__(self, caller_id):
                            self.caller = caller_id
                            self.state = CallState.DIALING
                            self.is_outgoing = True
                        async def hangup(self):
                            self.state = CallState.ENDED

                    placeholder = PlaceholderCall(number)
                    hass.data[DOMAIN][entry_id]["active_call"] = placeholder
                    from homeassistant.helpers.dispatcher import async_dispatcher_send
                    async_dispatcher_send(hass, f"{DOMAIN}_{entry_id}_call_update")

                    try:
                        outgoing_call = await sip_phone.call(number)
                        outgoing_call.is_outgoing = True
                        outgoing_call.dest_number = number
                        
                        if hass.data[DOMAIN][entry_id].get("active_call") == placeholder:
                            hass.data[DOMAIN][entry_id]["active_call"] = outgoing_call
                            async_dispatcher_send(hass, f"{DOMAIN}_{entry_id}_call_update")
                        else:
                            try:
                                await outgoing_call.hangup()
                            except Exception:
                                pass
                            continue
                        
                        async def monitor_call() -> None:
                            last_state = outgoing_call.state
                            while outgoing_call.state not in (CallState.ENDED, None):
                                if outgoing_call.state != last_state:
                                    last_state = outgoing_call.state
                                    LOGGER.info("SIP call state changed to: %s", last_state)
                                    async_dispatcher_send(hass, f"{DOMAIN}_{entry_id}_call_update")
                                await asyncio.sleep(0.5)
                            LOGGER.info("SIP call ended: %s", outgoing_call)
                            if hass.data[DOMAIN][entry_id].get("active_call") == outgoing_call:
                                    hass.data[DOMAIN][entry_id]["active_call"] = None
                            async_dispatcher_send(hass, f"{DOMAIN}_{entry_id}_call_update")

                        hass.async_create_task(monitor_call())
                    except Exception as err:
                        if hass.data[DOMAIN][entry_id].get("active_call") == placeholder:
                            hass.data[DOMAIN][entry_id]["active_call"] = None
                            async_dispatcher_send(hass, f"{DOMAIN}_{entry_id}_call_update")
                        raise HomeAssistantError(f"Failed to initiate call to {number}: {err}") from err

    async def handle_trigger_incoming_ring(call: ServiceCall) -> None:
        """Service handler to trigger a simulated incoming ring."""
        caller = call.data.get("caller", "4000")
        entry_ids = await async_resolve_entry_ids(call.data)
        for entry_id in entry_ids:
            if entry_id in hass.data[DOMAIN]:
                class MockSipCall:
                    def __init__(self, caller_id):
                        self.caller = caller_id
                        self.state = CallState.RINGING
                        self.is_outgoing = False
                    async def answer(self):
                        self.state = CallState.ANSWERED
                        LOGGER.info("Mock call answered")
                    async def hangup(self):
                        self.state = CallState.ENDED
                        LOGGER.info("Mock call hung up")
                    async def deny(self):
                        self.state = CallState.ENDED
                        LOGGER.info("Mock call denied")
                    async def audio_stream(self, frame_size=320, convert_16bit=True):
                        while self.state == CallState.ANSWERED:
                            yield b"\x00" * frame_size
                            await asyncio.sleep(frame_size / 16000.0)
                    async def write_audio_16bit(self, data):
                        pass

                mock_call = MockSipCall(caller)
                hass.data[DOMAIN][entry_id]["active_call"] = mock_call
                
                from homeassistant.helpers.dispatcher import async_dispatcher_send
                async_dispatcher_send(hass, f"{DOMAIN}_{entry_id}_call_update")
                
                async def monitor_call() -> None:
                    while mock_call.state != CallState.ENDED:
                        await asyncio.sleep(0.5)
                    if hass.data[DOMAIN][entry_id].get("active_call") == mock_call:
                        hass.data[DOMAIN][entry_id]["active_call"] = None
                    async_dispatcher_send(hass, f"{DOMAIN}_{entry_id}_call_update")
                    
                hass.async_create_task(monitor_call())

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

    if not hass.services.has_service(DOMAIN, SERVICE_ANSWER_CALL):
        hass.services.async_register(
            DOMAIN,
            SERVICE_ANSWER_CALL,
            handle_answer_call,
            schema=vol.Schema(
                {
                    vol.Optional("device_id"): vol.All(cv.ensure_list, [cv.string]),
                    vol.Optional("entity_id"): vol.All(cv.ensure_list, [cv.string]),
                }
            ),
        )

    if not hass.services.has_service(DOMAIN, SERVICE_HANGUP_CALL):
        hass.services.async_register(
            DOMAIN,
            SERVICE_HANGUP_CALL,
            handle_hangup_call,
            schema=vol.Schema(
                {
                    vol.Optional("device_id"): vol.All(cv.ensure_list, [cv.string]),
                    vol.Optional("entity_id"): vol.All(cv.ensure_list, [cv.string]),
                }
            ),
        )

    if not hass.services.has_service(DOMAIN, SERVICE_INITIATE_CALL):
        hass.services.async_register(
            DOMAIN,
            SERVICE_INITIATE_CALL,
            handle_initiate_call,
            schema=vol.Schema(
                {
                    vol.Required("number"): cv.string,
                    vol.Optional("device_id"): vol.All(cv.ensure_list, [cv.string]),
                    vol.Optional("entity_id"): vol.All(cv.ensure_list, [cv.string]),
                }
            ),
        )

    if not hass.services.has_service(DOMAIN, SERVICE_TRIGGER_INCOMING_RING):
        hass.services.async_register(
            DOMAIN,
            SERVICE_TRIGGER_INCOMING_RING,
            handle_trigger_incoming_ring,
            schema=vol.Schema(
                {
                    vol.Optional("caller", default="4000"): cv.string,
                    vol.Optional("device_id"): vol.All(cv.ensure_list, [cv.string]),
                    vol.Optional("entity_id"): vol.All(cv.ensure_list, [cv.string]),
                }
            ),
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Stop SIP Phone client
    if entry.entry_id in hass.data[DOMAIN]:
        sip_phone = hass.data[DOMAIN][entry.entry_id].get("sip_phone")
        if sip_phone:
            try:
                await sip_phone.stop()
            except Exception as err:
                LOGGER.error("Error stopping SIP phone client: %s", err)

    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

        # If no config entries left, remove services
        remaining_entries = [k for k in hass.data[DOMAIN].keys() if k != "websocket_view_registered"]
        if not remaining_entries:
            hass.services.async_remove(DOMAIN, SERVICE_OPEN_DOOR)
            hass.services.async_remove(DOMAIN, SERVICE_OPEN_DOOR_AT_POSITION)
            hass.services.async_remove(DOMAIN, SERVICE_SWITCH_CAMERA)
            hass.services.async_remove(DOMAIN, SERVICE_GET_SIP_CREDENTIALS)
            hass.services.async_remove(DOMAIN, SERVICE_ANSWER_CALL)
            hass.services.async_remove(DOMAIN, SERVICE_HANGUP_CALL)
            hass.services.async_remove(DOMAIN, SERVICE_INITIATE_CALL)
            hass.services.async_remove(DOMAIN, SERVICE_TRIGGER_INCOMING_RING)
            if "websocket_view_registered" in hass.data[DOMAIN]:
                hass.data[DOMAIN].pop("websocket_view_registered")

    return unload_ok
