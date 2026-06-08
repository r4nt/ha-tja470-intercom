"""Tests for Hager TJA470 Intercom component initialization and services."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tja470_intercom.const import CONF_UUID, CONF_COOKIES, DOMAIN
from aiotja470_intercom.models import ProvisioningInfo, Manifest, SipInfo, CalledElement

pytestmark = pytest.mark.asyncio


async def test_setup_unload_entry(hass: HomeAssistant) -> None:
    """Test setting up and unloading the Hager TJA470 Intercom integration config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "host": "192.168.42.2",
            "username": "manuel",
            "password": "pwd",
            CONF_UUID: "some-uuid",
            CONF_COOKIES: {"JSESSIONID": "node0abc"},
        },
    )
    entry.add_to_hass(hass)

    mock_client = MagicMock()
    mock_client.get_manifest = AsyncMock(return_value=Manifest(raw_data={"fw": "2.7.3"}))
    mock_client.get_provisioning = AsyncMock(
        return_value=ProvisioningInfo(
            sip_info=SipInfo(sip_id="6004", sip_password="pwd"),
            rtsp_video_url="rtsp://some_url",
            http_video_url="http://some_http_url",
            local_ip_address="192.168.42.2",
            door_release_allowed=True,
            called_elements=[
                CalledElement(sip_id="4000", name="Driveway", order=0),
                CalledElement(sip_id="4001", name="Frontdoor", order=1),
            ],
        )
    )
    mock_client.get_cookies = MagicMock(return_value={"JSESSIONID": "node0abc"})

    with patch(
        "custom_components.tja470_intercom.TJA470IntercomClient",
        return_value=mock_client,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert entry.entry_id in hass.data[DOMAIN]

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.entry_id not in hass.data[DOMAIN]


async def test_services(hass: HomeAssistant) -> None:
    """Test registering and calling the custom integration services."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "host": "192.168.42.2",
            "username": "manuel",
            "password": "pwd",
            CONF_UUID: "some-uuid",
        },
    )
    entry.add_to_hass(hass)

    mock_client = MagicMock()
    mock_client.get_manifest = AsyncMock(return_value=Manifest(raw_data={"fw": "2.7.3"}))
    mock_client.get_provisioning = AsyncMock(
        return_value=ProvisioningInfo(
            sip_info=SipInfo(sip_id="6004", sip_password="pwd"),
            rtsp_video_url="rtsp://some_url",
            http_video_url="http://some_http_url",
            local_ip_address="192.168.42.2",
            door_release_allowed=True,
        )
    )
    mock_client.open_door = AsyncMock()
    mock_client.open_door_at_position = AsyncMock()
    mock_client.switch_camera = AsyncMock()
    mock_client.switch_to_camera_position = AsyncMock()
    mock_client.get_cookies = MagicMock(return_value={})

    with patch(
        "custom_components.tja470_intercom.TJA470IntercomClient",
        return_value=mock_client,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Call open_door service
        await hass.services.async_call(
            DOMAIN,
            "open_door",
            {"door_id": 2},
            blocking=True,
        )
        mock_client.open_door.assert_called_once_with(door_id=2)

        # Call open_door_at_position service
        await hass.services.async_call(
            DOMAIN,
            "open_door_at_position",
            {"position": 0, "door_id": 1},
            blocking=True,
        )
        mock_client.open_door_at_position.assert_called_once_with(
            "some-uuid", 0, door_id=1, max_attempts=10
        )

        # Call switch_camera service with position
        await hass.services.async_call(
            DOMAIN,
            "switch_camera",
            {"position": 1},
            blocking=True,
        )
        mock_client.switch_to_camera_position.assert_called_once_with(
            "some-uuid", 1, max_attempts=10
        )

        # Call switch_camera service without position (toggles next camera)
        await hass.services.async_call(
            DOMAIN,
            "switch_camera",
            {},
            blocking=True,
        )
        mock_client.switch_camera.assert_called_once_with("some-uuid")

        # Call get_sip_credentials service (returns response)
        response = await hass.services.async_call(
            DOMAIN,
            "get_sip_credentials",
            {},
            blocking=True,
            return_response=True,
        )
        assert response == {
            "sip_registrar": "192.168.42.2",
            "sip_username": "6004",
            "sip_password": "pwd",
        }


async def test_lovelace_resource_registration(hass: HomeAssistant) -> None:
    """Test dynamic Lovelace resource registration."""
    from custom_components.tja470_intercom import async_register_lovelace_resource
    from homeassistant.const import EVENT_HOMEASSISTANT_STARTED

    mock_resources = MagicMock()
    mock_resources.loaded = False
    mock_resources.async_load = AsyncMock()
    mock_resources.async_items = MagicMock(return_value=[])
    mock_resources.async_create_item = AsyncMock()
    mock_resources.async_update_item = AsyncMock()

    mock_lovelace = MagicMock()
    mock_lovelace.resources = mock_resources
    mock_lovelace.resource_mode = "storage"

    hass.data["lovelace"] = mock_lovelace

    # Mock hass.http
    hass.http = MagicMock()
    hass.http.async_register_static_paths = AsyncMock()

    # Test case 1: hass.is_running is True -> registers immediately
    with patch.object(hass, "is_running", True):
        await async_register_lovelace_resource(hass)

    # Verify load was called since loaded is False
    mock_resources.async_load.assert_called_once()

    # Verify the item is created
    mock_resources.async_create_item.assert_called_once_with({
        "res_type": "module",
        "url": "/tja470-intercom/tja470-intercom-card.js?v=1.0.0",
    })

    # Test case 2: hass.is_running is False -> registers after EVENT_HOMEASSISTANT_STARTED
    mock_resources.async_load.reset_mock()
    mock_resources.async_create_item.reset_mock()
    mock_resources.loaded = False

    with patch.object(hass, "is_running", False):
        await async_register_lovelace_resource(hass)

    # Should NOT be registered immediately since hass is not running
    mock_resources.async_create_item.assert_not_called()

    # Fire the event
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()

    # Now it should be registered
    mock_resources.async_create_item.assert_called_once_with({
        "res_type": "module",
        "url": "/tja470-intercom/tja470-intercom-card.js?v=1.0.0",
    })

    # Test case 3: updating resource when version is different
    mock_resources.async_load.reset_mock()
    mock_resources.async_create_item.reset_mock()
    mock_resources.loaded = True
    mock_resources.async_items = MagicMock(return_value=[
        {"id": "card_id", "url": "/tja470-intercom/tja470-intercom-card.js?v=0.9.0"}
    ])

    with patch.object(hass, "is_running", True):
        await async_register_lovelace_resource(hass)

    mock_resources.async_load.assert_not_called()
    mock_resources.async_create_item.assert_not_called()
    mock_resources.async_update_item.assert_called_once_with(
        "card_id",
        {"res_type": "module", "url": "/tja470-intercom/tja470-intercom-card.js?v=1.0.0"}
    )


async def test_call_services_and_stream(hass: HomeAssistant, mock_sip_phone) -> None:
    """Test the newly added call services."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "host": "192.168.42.2",
            "username": "manuel",
            "password": "pwd",
            CONF_UUID: "some-uuid",
        },
    )
    entry.add_to_hass(hass)

    mock_client = MagicMock()
    mock_client.get_manifest = AsyncMock(return_value=Manifest(raw_data={"fw": "2.7.3"}))
    mock_client.get_provisioning = AsyncMock(
        return_value=ProvisioningInfo(
            sip_info=SipInfo(sip_id="6004", sip_password="pwd"),
            rtsp_video_url="rtsp://some_url",
            http_video_url="http://some_http_url",
            local_ip_address="192.168.42.2",
            door_release_allowed=True,
        )
    )
    mock_client.get_cookies = MagicMock(return_value={})

    with patch(
        "custom_components.tja470_intercom.TJA470IntercomClient",
        return_value=mock_client,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Trigger simulated incoming ring
        await hass.services.async_call(
            DOMAIN,
            "trigger_incoming_ring",
            {"caller": "6001"},
            blocking=True,
        )
        
        active_call = hass.data[DOMAIN][entry.entry_id]["active_call"]
        assert active_call is not None
        assert active_call.caller == "6001"
        assert active_call.is_outgoing is False

        # Verify camera entity call_state is "ringing"
        camera_entity_ids = hass.states.async_entity_ids("camera")
        assert len(camera_entity_ids) > 0
        camera_state = hass.states.get(camera_entity_ids[0])
        assert camera_state.attributes["call_state"] == "ringing"

        # Answer active call
        await hass.services.async_call(
            DOMAIN,
            "answer_call",
            {},
            blocking=True,
        )
        from pyVoIP.VoIP import CallState
        assert active_call.state == CallState.ANSWERED
        
        camera_state = hass.states.get(camera_entity_ids[0])
        assert camera_state.attributes["call_state"] == "answered"

        # Hang up active call
        await hass.services.async_call(
            DOMAIN,
            "hangup_call",
            {},
            blocking=True,
        )
        assert hass.data[DOMAIN][entry.entry_id]["active_call"] is None
        camera_state = hass.states.get(camera_entity_ids[0])
        assert camera_state.attributes["call_state"] == "idle"

        # Test initiate_call (outgoing call)
        mock_outgoing_call = MagicMock()
        mock_outgoing_call.state = CallState.DIALING
        mock_outgoing_call.caller = "6002"
        mock_outgoing_call.hangup = AsyncMock()

        mock_sip_phone.call = AsyncMock(return_value=mock_outgoing_call)

        await hass.services.async_call(
            DOMAIN,
            "initiate_call",
            {"number": "6002"},
            blocking=True,
        )

        active_call = hass.data[DOMAIN][entry.entry_id]["active_call"]
        assert active_call is not None
        assert active_call.caller == "6002"
        assert active_call.is_outgoing is True

        camera_state = hass.states.get(camera_entity_ids[0])
        assert camera_state.attributes["call_state"] == "dialing"

        # Hang up active call
        await hass.services.async_call(
            DOMAIN,
            "hangup_call",
            {},
            blocking=True,
        )
        assert hass.data[DOMAIN][entry.entry_id]["active_call"] is None
        camera_state = hass.states.get(camera_entity_ids[0])
        assert camera_state.attributes["call_state"] == "idle"


