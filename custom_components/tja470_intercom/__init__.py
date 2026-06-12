"""The Hager TJA470 Intercom integration."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import voluptuous as vol
from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.issue_registry import IssueSeverity, async_create_issue, async_delete_issue
from homeassistant.helpers.typing import ConfigType

from aiotja470_intercom import TJA470IntercomClient, AiohttpRunner, TJA470SipPhone, TJA470SipCall
from aiotja470_intercom.exceptions import TJA470AuthError, TJA470Error

from .const import CONF_COOKIES, CONF_UUID, DOMAIN, LOGGER
from .coordinator import TJA470Coordinator

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS = [Platform.CAMERA, Platform.BUTTON, Platform.SENSOR]

SERVICE_OPEN_DOOR = "open_door"
SERVICE_OPEN_DOOR_AT_POSITION = "open_door_at_position"
SERVICE_SWITCH_CAMERA = "switch_camera"
SERVICE_GET_SIP_CREDENTIALS = "get_sip_credentials"
SERVICE_ANSWER_CALL = "answer_call"
SERVICE_HANGUP_CALL = "hangup_call"
SERVICE_INITIATE_CALL = "initiate_call"
SERVICE_TRIGGER_INCOMING_RING = "trigger_incoming_ring"


@dataclass
class TJA470RuntimeData:
    """Runtime data stored on each config entry."""

    client: TJA470IntercomClient
    coordinator: TJA470Coordinator
    sip_phone: TJA470SipPhone
    active_call: Any = field(default=None)


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

        entry = hass.config_entries.async_get_entry(entry_id) if entry_id else None
        if not entry or entry.domain != DOMAIN:
            return web.Response(status=400, text="Invalid entry_id")

        try:
            active_call = entry.runtime_data.active_call
        except AttributeError:
            active_call = None

        if not active_call:
            return web.Response(status=400, text="No active call")

        ws = web.WebSocketResponse()
        await ws.prepare(request)

        LOGGER.info("Websocket audio stream connected for call: %s", active_call)

        async def send_audio():
            from pyVoIP.VoIP import CallState
            try:
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

        await asyncio.gather(send_audio(), receive_audio())
        LOGGER.info("Websocket audio stream disconnected")
        return ws


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the TJA470 Intercom domain and register services."""
    hass.data.setdefault(DOMAIN, {})

    def _get_runtime(entry_id: str) -> TJA470RuntimeData | None:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            return None
        try:
            return entry.runtime_data
        except AttributeError:
            return None

    async def _resolve_entry_ids(call_data: dict) -> list[str]:
        device_ids = call_data.get("device_id", [])
        entity_ids = call_data.get("entity_id", [])
        entry_ids: list[str] = []

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
            entry_ids = [e.entry_id for e in hass.config_entries.async_entries(DOMAIN)]

        return list(set(entry_ids))

    async def _resolve_clients(device_ids: list[str]) -> list[TJA470IntercomClient]:
        clients: list[TJA470IntercomClient] = []
        for entry_id in await _resolve_entry_ids({"device_id": device_ids}):
            runtime = _get_runtime(entry_id)
            if runtime:
                clients.append(runtime.client)
        return list(set(clients))

    async def handle_open_door(call: ServiceCall) -> None:
        device_ids = call.data.get("device_id", [])
        door_id = call.data.get("door_id", 1)
        clients = await _resolve_clients(device_ids)
        if not clients:
            raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_clients_found"
        )
        for cli in clients:
            try:
                await cli.open_door(door_id=door_id)
            except TJA470Error as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="open_door_failed",
                    translation_placeholders={"error": str(err)},
                ) from err

    async def handle_open_door_at_position(call: ServiceCall) -> None:
        device_ids = call.data.get("device_id", [])
        position = call.data["position"]
        door_id = call.data.get("door_id", 1)
        max_attempts = call.data.get("max_attempts", 10)
        clients = await _resolve_clients(device_ids)
        if not clients:
            raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_clients_found"
        )
        for cli in clients:
            client_uuid = None
            for entry in hass.config_entries.async_entries(DOMAIN):
                try:
                    if entry.runtime_data.client == cli:
                        client_uuid = entry.data[CONF_UUID]
                        break
                except AttributeError:
                    pass
            if not client_uuid:
                continue
            try:
                await cli.open_door_at_position(
                    client_uuid, position, door_id=door_id, max_attempts=max_attempts
                )
            except TJA470Error as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="open_door_at_position_failed",
                    translation_placeholders={"position": str(position), "error": str(err)},
                ) from err

    async def handle_switch_camera(call: ServiceCall) -> None:
        device_ids = call.data.get("device_id", [])
        position = call.data.get("position")
        max_attempts = call.data.get("max_attempts", 10)
        clients = await _resolve_clients(device_ids)
        if not clients:
            raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_clients_found"
        )
        for cli in clients:
            client_uuid = None
            for entry in hass.config_entries.async_entries(DOMAIN):
                try:
                    if entry.runtime_data.client == cli:
                        client_uuid = entry.data[CONF_UUID]
                        break
                except AttributeError:
                    pass
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
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="switch_camera_failed",
                    translation_placeholders={"error": str(err)},
                ) from err

    async def handle_get_sip_credentials(call: ServiceCall) -> ServiceResponse:
        device_ids = call.data.get("device_id", [])
        clients = await _resolve_clients(device_ids)
        if not clients:
            raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_clients_found"
        )
        cli = clients[0]
        coordinator = None
        for entry in hass.config_entries.async_entries(DOMAIN):
            try:
                if entry.runtime_data.client == cli:
                    coordinator = entry.runtime_data.coordinator
                    break
            except AttributeError:
                pass
        if not coordinator or not coordinator.data or "provisioning" not in coordinator.data:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="provisioning_not_loaded"
            )
        prov = coordinator.data["provisioning"]
        return {
            "sip_registrar": coordinator.entry.data[CONF_HOST],
            "sip_username": prov.sip_info.sip_id,
            "sip_password": prov.sip_info.sip_password,
        }

    async def handle_answer_call(call: ServiceCall) -> None:
        for entry_id in await _resolve_entry_ids(call.data):
            runtime = _get_runtime(entry_id)
            if runtime and runtime.active_call:
                try:
                    await runtime.active_call.answer()
                except Exception as err:
                    raise HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="answer_call_failed",
                        translation_placeholders={"error": str(err)},
                    ) from err
                finally:
                    from homeassistant.helpers.dispatcher import async_dispatcher_send
                    async_dispatcher_send(hass, f"{DOMAIN}_{entry_id}_call_update")

    async def handle_hangup_call(call: ServiceCall) -> None:
        for entry_id in await _resolve_entry_ids(call.data):
            runtime = _get_runtime(entry_id)
            if runtime and runtime.active_call:
                try:
                    await runtime.active_call.hangup()
                except Exception as err:
                    raise HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="hangup_call_failed",
                        translation_placeholders={"error": str(err)},
                    ) from err
                finally:
                    runtime.active_call = None
                    from homeassistant.helpers.dispatcher import async_dispatcher_send
                    async_dispatcher_send(hass, f"{DOMAIN}_{entry_id}_call_update")

    async def handle_initiate_call(call: ServiceCall) -> None:
        from pyVoIP.VoIP import CallState
        number = call.data["number"]
        for entry_id in await _resolve_entry_ids(call.data):
            runtime = _get_runtime(entry_id)
            if not runtime or not runtime.sip_phone:
                continue
            if runtime.active_call:
                try:
                    await runtime.active_call.hangup()
                except Exception as e:
                    LOGGER.debug("Failed to hang up previous call: %s", e)

            class PlaceholderCall:
                def __init__(self, caller_id):
                    self.caller = caller_id
                    self.state = CallState.DIALING
                    self.is_outgoing = True
                async def hangup(self):
                    self.state = CallState.ENDED

            placeholder = PlaceholderCall(number)
            runtime.active_call = placeholder
            from homeassistant.helpers.dispatcher import async_dispatcher_send
            async_dispatcher_send(hass, f"{DOMAIN}_{entry_id}_call_update")

            try:
                outgoing_call = await runtime.sip_phone.call(number)
                outgoing_call.is_outgoing = True
                outgoing_call.dest_number = number

                if runtime.active_call == placeholder:
                    runtime.active_call = outgoing_call
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
                    rt = _get_runtime(entry_id)
                    if rt and rt.active_call == outgoing_call:
                        rt.active_call = None
                    async_dispatcher_send(hass, f"{DOMAIN}_{entry_id}_call_update")

                hass.async_create_task(monitor_call())
            except Exception as err:
                if runtime.active_call == placeholder:
                    runtime.active_call = None
                    async_dispatcher_send(hass, f"{DOMAIN}_{entry_id}_call_update")
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="initiate_call_failed",
                    translation_placeholders={"number": number, "error": str(err)},
                ) from err

    async def handle_trigger_incoming_ring(call: ServiceCall) -> None:
        from pyVoIP.VoIP import CallState
        caller = call.data.get("caller", "4000")
        for entry_id in await _resolve_entry_ids(call.data):
            runtime = _get_runtime(entry_id)
            if not runtime:
                continue

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
            runtime.active_call = mock_call
            from homeassistant.helpers.dispatcher import async_dispatcher_send
            async_dispatcher_send(hass, f"{DOMAIN}_{entry_id}_call_update")

            async def monitor_call() -> None:
                while mock_call.state != CallState.ENDED:
                    await asyncio.sleep(0.5)
                rt = _get_runtime(entry_id)
                if rt and rt.active_call == mock_call:
                    rt.active_call = None
                async_dispatcher_send(hass, f"{DOMAIN}_{entry_id}_call_update")

            hass.async_create_task(monitor_call())

    hass.services.async_register(
        DOMAIN, SERVICE_OPEN_DOOR, handle_open_door,
        schema=vol.Schema({
            vol.Optional("device_id"): vol.All(cv.ensure_list, [cv.string]),
            vol.Optional("door_id", default=1): cv.positive_int,
        }),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_OPEN_DOOR_AT_POSITION, handle_open_door_at_position,
        schema=vol.Schema({
            vol.Optional("device_id"): vol.All(cv.ensure_list, [cv.string]),
            vol.Required("position"): cv.positive_int,
            vol.Optional("door_id", default=1): cv.positive_int,
            vol.Optional("max_attempts", default=10): cv.positive_int,
        }),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SWITCH_CAMERA, handle_switch_camera,
        schema=vol.Schema({
            vol.Optional("device_id"): vol.All(cv.ensure_list, [cv.string]),
            vol.Optional("position"): cv.positive_int,
            vol.Optional("max_attempts", default=10): cv.positive_int,
        }),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_GET_SIP_CREDENTIALS, handle_get_sip_credentials,
        schema=vol.Schema({
            vol.Optional("device_id"): vol.All(cv.ensure_list, [cv.string]),
        }),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_ANSWER_CALL, handle_answer_call,
        schema=vol.Schema({
            vol.Optional("device_id"): vol.All(cv.ensure_list, [cv.string]),
            vol.Optional("entity_id"): vol.All(cv.ensure_list, [cv.string]),
        }),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_HANGUP_CALL, handle_hangup_call,
        schema=vol.Schema({
            vol.Optional("device_id"): vol.All(cv.ensure_list, [cv.string]),
            vol.Optional("entity_id"): vol.All(cv.ensure_list, [cv.string]),
        }),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_INITIATE_CALL, handle_initiate_call,
        schema=vol.Schema({
            vol.Required("number"): cv.string,
            vol.Optional("device_id"): vol.All(cv.ensure_list, [cv.string]),
            vol.Optional("entity_id"): vol.All(cv.ensure_list, [cv.string]),
        }),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_TRIGGER_INCOMING_RING, handle_trigger_incoming_ring,
        schema=vol.Schema({
            vol.Optional("caller", default="4000"): cv.string,
            vol.Optional("device_id"): vol.All(cv.ensure_list, [cv.string]),
            vol.Optional("entity_id"): vol.All(cv.ensure_list, [cv.string]),
        }),
    )

    return True


async def async_register_lovelace_resource(hass: HomeAssistant) -> None:
    """Register Lovelace resource dynamically."""
    import os
    www_dir = os.path.join(os.path.dirname(__file__), "www")

    if hasattr(hass, "http"):
        from homeassistant.components.http import StaticPathConfig
        await hass.http.async_register_static_paths([
            StaticPathConfig("/tja470-intercom", www_dir, False)
        ])

    async def async_register(event=None) -> None:
        if "lovelace" not in hass.data:
            return
        lovelace = hass.data["lovelace"]
        if not hasattr(lovelace, "resources") or getattr(lovelace, "resource_mode", None) != "storage":
            return
        resources = lovelace.resources
        if not resources.loaded:
            await resources.async_load()

        url = "/tja470-intercom/tja470-intercom-card.js?v=1.1.9"
        for item in resources.async_items():
            if item.get("url", "").startswith("/tja470-intercom/tja470-intercom-card.js"):
                if item.get("url") != url:
                    await resources.async_update_item(item["id"], {"res_type": "module", "url": url})
                return
        await resources.async_create_item({"res_type": "module", "url": url})

    if hass.is_running:
        await async_register()
    else:
        from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, async_register)


async def async_register_custom_panel(hass: HomeAssistant) -> None:
    """Register custom sidebar panel dynamically."""
    url_path = "intercom"
    if url_path in hass.data.get("frontend_panels", {}):
        return
    from homeassistant.components import panel_custom
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=url_path,
        webcomponent_name="tja470-intercom-panel",
        sidebar_title="Intercom",
        sidebar_icon="mdi:phone-in-talk",
        module_url="/tja470-intercom/tja470-intercom-panel.js?v=1.1.9",
        require_admin=False,
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Hager TJA470 Intercom from a config entry."""
    await async_register_lovelace_resource(hass)
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

    from homeassistant.components.network import async_get_source_ip
    local_ip = await async_get_source_ip(hass, host)

    prov = coordinator.data["provisioning"]
    sip_phone = TJA470SipPhone(
        host=host,
        sip_id=prov.sip_info.sip_id,
        sip_password=prov.sip_info.sip_password,
        local_ip=local_ip,
    )

    entry.runtime_data = TJA470RuntimeData(
        client=client,
        coordinator=coordinator,
        sip_phone=sip_phone,
    )

    async def handle_incoming_call(call: TJA470SipCall) -> None:
        LOGGER.info("Incoming SIP call from %s", call.caller)
        call.is_outgoing = False
        entry.runtime_data.active_call = call
        from homeassistant.helpers.dispatcher import async_dispatcher_send
        async_dispatcher_send(hass, f"{DOMAIN}_{entry.entry_id}_call_update")

        async def send_notifications() -> None:
            notify_devices = entry.options.get("notify_devices", [])
            if not notify_devices:
                return
            caller_name = call.caller
            if coordinator.data and "provisioning" in coordinator.data:
                for element in coordinator.data["provisioning"].called_elements:
                    if element.sip_id == call.caller and element.name:
                        caller_name = element.name
                        break
            for device in notify_devices:
                service_name = device if not device.startswith("notify.") else device[7:]
                LOGGER.debug("Sending call notification via service notify.%s", service_name)
                try:
                    await hass.services.async_call(
                        "notify", service_name,
                        {
                            "title": "Intercom Call",
                            "message": f"Incoming call from {caller_name}",
                            "data": {
                                "ttl": 0,
                                "priority": "high",
                                "channel": "Intercom",
                                "clickAction": "/intercom",
                            },
                        },
                    )
                except Exception as err:
                    LOGGER.error("Failed to send notification to %s: %s", device, err)

        hass.async_create_task(send_notifications())

        async def monitor_call() -> None:
            from pyVoIP.VoIP import CallState
            while call.state not in (CallState.ENDED, None):
                await asyncio.sleep(0.5)
            LOGGER.info("SIP call ended: %s", call)
            if entry.runtime_data.active_call == call:
                entry.runtime_data.active_call = None
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
        async_delete_issue(hass, DOMAIN, f"sip_phone_failed_{entry.entry_id}")
    except Exception as err:
        LOGGER.error("Failed to start SIP phone: %s", err)
        async_create_issue(
            hass,
            DOMAIN,
            f"sip_phone_failed_{entry.entry_id}",
            is_fixable=False,
            severity=IssueSeverity.WARNING,
            translation_key="sip_phone_failed",
            translation_placeholders={"host": host},
        )

    if "websocket_view_registered" not in hass.data[DOMAIN]:
        hass.http.register_view(TJA470AudioStreamView())
        hass.data[DOMAIN]["websocket_view_registered"] = True

    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=f"TJA470 Intercom Controller ({host})",
        manufacturer="Hager",
        model="TJA470",
        sw_version=coordinator.data["manifest"].fw,
    )
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

    from homeassistant.core import callback

    @callback
    def _async_remove_stale_door_devices() -> None:
        """Remove door station devices that are no longer in provisioning data."""
        prov = coordinator.data.get("provisioning") if coordinator.data else None
        if prov is None:
            return
        current_sip_ids = {e.sip_id for e in prov.called_elements if e.order is not None}
        device_reg = dr.async_get(hass)
        for device_entry in dr.async_entries_for_config_entry(device_reg, entry.entry_id):
            for domain, identifier in device_entry.identifiers:
                if domain == DOMAIN and identifier.startswith("door_"):
                    if identifier[len("door_"):] not in current_sip_ids:
                        device_reg.async_remove_device(device_entry.id)
                    break

    entry.async_on_unload(coordinator.async_add_listener(_async_remove_stale_door_devices))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    try:
        sip_phone = entry.runtime_data.sip_phone
    except AttributeError:
        sip_phone = None

    if sip_phone:
        try:
            await sip_phone.stop()
        except Exception as err:
            LOGGER.error("Error stopping SIP phone client: %s", err)

    async_delete_issue(hass, DOMAIN, f"sip_phone_failed_{entry.entry_id}")
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
