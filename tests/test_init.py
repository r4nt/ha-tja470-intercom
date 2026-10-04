"""Tests for Hager TJA470 Intercom component initialization and services."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tja470_intercom.const import CONF_UUID, CONF_COOKIES, DOMAIN
from aiotja470_intercom.exceptions import TJA470Error
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
    mock_client.get_software_version = AsyncMock(return_value="4.0.2")
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

        assert entry.state == ConfigEntryState.LOADED

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state == ConfigEntryState.NOT_LOADED


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
    mock_client.get_software_version = AsyncMock(return_value="4.0.2")
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

        # Without door_id, the library's default (the client's own SIP ID) is used
        mock_client.open_door.reset_mock()
        await hass.services.async_call(
            DOMAIN,
            "open_door",
            {},
            blocking=True,
        )
        mock_client.open_door.assert_called_once_with(door_id=None)

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
        "url": "/tja470-intercom/tja470-intercom-card.js?v=1.3.5",
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
        "url": "/tja470-intercom/tja470-intercom-card.js?v=1.3.5",
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
        {"res_type": "module", "url": "/tja470-intercom/tja470-intercom-card.js?v=1.3.5"}
    )


async def test_custom_panel_registration(hass: HomeAssistant) -> None:
    """Test dynamic custom panel registration."""
    from custom_components.tja470_intercom import async_register_custom_panel

    hass.data["frontend_panels"] = {}

    with patch(
        "homeassistant.components.panel_custom.async_register_panel"
    ) as mock_register:
        await async_register_custom_panel(hass)

        mock_register.assert_called_once_with(
            hass,
            frontend_url_path="intercom",
            webcomponent_name="tja470-intercom-panel",
            sidebar_title="Intercom",
            sidebar_icon="mdi:phone-in-talk",
            module_url="/tja470-intercom/tja470-intercom-panel.js?v=1.3.5",
            require_admin=False,
        )

    # Test case 2: Panel already registered -> skips registration
    hass.data["frontend_panels"] = {"intercom": MagicMock()}
    with patch(
        "homeassistant.components.panel_custom.async_register_panel"
    ) as mock_register:
        await async_register_custom_panel(hass)

        mock_register.assert_not_called()


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
    mock_client.get_software_version = AsyncMock(return_value="4.0.2")
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
        
        active_call = entry.runtime_data.active_call
        assert active_call is not None
        assert active_call.caller == "6001"
        assert active_call.is_outgoing is False

        # Verify call_state and caller sensors
        sensor_entity_ids = hass.states.async_entity_ids("sensor")
        call_state_eid = next(eid for eid in sensor_entity_ids if eid.endswith("_call_state"))
        caller_eid = next(eid for eid in sensor_entity_ids if eid.endswith("_caller"))
        assert hass.states.get(call_state_eid).state == "ringing"
        assert hass.states.get(caller_eid).state == "6001"

        # Answer active call
        await hass.services.async_call(
            DOMAIN,
            "answer_call",
            {},
            blocking=True,
        )
        from pyVoIP.VoIP import CallState
        assert active_call.state == CallState.ANSWERED
        
        assert hass.states.get(call_state_eid).state == "answered"

        # Hang up active call
        await hass.services.async_call(
            DOMAIN,
            "hangup_call",
            {},
            blocking=True,
        )
        assert entry.runtime_data.active_call is None
        assert hass.states.get(call_state_eid).state == "idle"

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

        active_call = entry.runtime_data.active_call
        assert active_call is not None
        assert active_call.caller == "6002"
        assert active_call.is_outgoing is True

        assert hass.states.get(call_state_eid).state == "dialing"
        assert hass.states.get(caller_eid).state == "6002"

        # Test initiating a call while a call is already active
        mock_outgoing_call2 = MagicMock()
        mock_outgoing_call2.state = CallState.DIALING
        mock_outgoing_call2.caller = "6003"
        mock_outgoing_call2.hangup = AsyncMock()

        mock_sip_phone.call = AsyncMock(return_value=mock_outgoing_call2)

        await hass.services.async_call(
            DOMAIN,
            "initiate_call",
            {"number": "6003"},
            blocking=True,
        )

        # The previous call should have been hung up
        mock_outgoing_call.hangup.assert_called_once()

        active_call = entry.runtime_data.active_call
        assert active_call is not None
        assert active_call.caller == "6003"

        # Hang up active call
        await hass.services.async_call(
            DOMAIN,
            "hangup_call",
            {},
            blocking=True,
        )
        assert entry.runtime_data.active_call is None
        assert hass.states.get(call_state_eid).state == "idle"


async def test_options_flow(hass: HomeAssistant) -> None:
    """Test options flow."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "host": "192.168.42.2",
            "username": "manuel",
            "password": "pwd",
            CONF_UUID: "some-uuid",
        },
        options={},
    )
    entry.add_to_hass(hass)

    # Simulate options flow step
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "form"
    assert result["step_id"] == "init"

    # Update options with notify_devices_text
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "notify_devices_text": "mobile_app_phone1, mobile_app_phone2",
        },
    )
    assert result["type"] == "create_entry"
    assert entry.options == {
        "notify_devices": ["mobile_app_phone1", "mobile_app_phone2"],
        "snapshot_retention_days": 3,
    }


async def test_options_flow_with_device_trackers(hass: HomeAssistant) -> None:
    """Test options flow shows device tracker last seen next to mobile app notify targets."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "host": "192.168.42.2",
            "username": "manuel",
            "password": "pwd",
            CONF_UUID: "some-uuid",
        },
        options={},
    )
    entry.add_to_hass(hass)

    # Mock the mobile_app config entry
    mobile_entry = MockConfigEntry(
        domain="mobile_app",
        data={
            "device_id": "my_new_phone",
            "device_name": "My New Phone",
        },
        entry_id="mobile_app_entry_id",
    )
    mobile_entry.add_to_hass(hass)

    # Register in device registry
    from homeassistant.helpers import device_registry as dr, entity_registry as er
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=mobile_entry.entry_id,
        identifiers={("mobile_app", "my_new_phone")},
        name="My New Phone",
    )

    # Register device tracker in entity registry
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create(
        domain="device_tracker",
        platform="mobile_app",
        unique_id="tracker_unique_id",
        config_entry=mobile_entry,
        device_id=device.id,
        suggested_object_id="my_new_phone",
    )

    # Add a device_tracker state to hass
    hass.states.async_set("device_tracker.my_new_phone", "home")

    # Initialize options flow
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "form"
    assert result["step_id"] == "init"

    # The schema should offer the notify.mobile_app_my_new_phone service
    schema = result["data_schema"].schema
    assert "notify_devices" in schema
    assert "notify.mobile_app_my_new_phone" in schema["notify_devices"].options

    # The description placeholders should contain the matching tracker last seen
    assert "my_new_phone" in result["description_placeholders"]["device_trackers"]

    # Configure it
    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "notify_devices": ["notify.mobile_app_my_new_phone"],
        },
    )
    assert result2["type"] == "create_entry"
    assert entry.options == {
        "notify_devices": ["notify.mobile_app_my_new_phone"],
        "snapshot_retention_days": 3,
    }


async def test_incoming_call_notification(hass: HomeAssistant, mock_sip_phone) -> None:
    """Test incoming call notifications are dispatched."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "host": "192.168.42.2",
            "username": "manuel",
            "password": "pwd",
            CONF_UUID: "some-uuid",
        },
        options={
            "notify_devices": ["mobile_app_phone1", "mobile_app_phone2"],
        },
    )
    entry.add_to_hass(hass)

    mock_client = MagicMock()
    mock_client.get_software_version = AsyncMock(return_value="4.0.2")
    mock_client.get_manifest = AsyncMock(return_value=Manifest(raw_data={"fw": "2.7.3"}))
    from aiotja470_intercom.models import CalledElement
    mock_client.get_provisioning = AsyncMock(
        return_value=ProvisioningInfo(
            sip_info=SipInfo(sip_id="6004", sip_password="pwd"),
            rtsp_video_url="rtsp://some_url",
            http_video_url="http://some_http_url",
            local_ip_address="192.168.42.2",
            door_release_allowed=True,
            called_elements=[
                CalledElement(sip_id="6001", name="Front Door", order=1),
            ]
        )
    )
    mock_client.get_cookies = MagicMock(return_value={})

    with patch(
        "custom_components.tja470_intercom.TJA470IntercomClient",
        return_value=mock_client,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Get registered callback
        mock_sip_phone.register_incoming_call_callback.assert_called_once()
        incoming_callback = mock_sip_phone.register_incoming_call_callback.call_args[0][0]

        # Create a mock incoming call from 6001 (which resolves to "Front Door")
        from pyVoIP.VoIP import CallState
        mock_call = MagicMock()
        mock_call.caller = "6001"
        mock_call.state = CallState.RINGING

        # Spy on services
        calls = []
        @callback
        def record_call(service_call):
            calls.append(service_call)

        hass.services.async_register(
            "notify", "mobile_app_phone1", record_call
        )
        hass.services.async_register(
            "notify", "mobile_app_phone2", record_call
        )

        # Trigger incoming call callback
        await incoming_callback(mock_call)
        mock_call.state = CallState.ENDED
        await hass.async_block_till_done()

        # Verify both notify services were called
        assert len(calls) == 2
        for service_call in calls:
            assert service_call.data["title"] == "Intercom Call"
            assert service_call.data["message"] == "Incoming call from Front Door"
            assert service_call.data["data"] == {
                "ttl": 0,
                "priority": "high",
                "channel": "Intercom",
                "clickAction": "/intercom",
            }


async def test_coordinator_update_failure_makes_entities_unavailable(
    hass: HomeAssistant,
) -> None:
    """Test that a coordinator update failure marks entities as unavailable."""
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
    mock_client.get_software_version = AsyncMock(return_value="4.0.2")
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

        # Entities are available after initial setup
        camera_ids = hass.states.async_entity_ids("camera")
        assert len(camera_ids) > 0
        assert hass.states.get(camera_ids[0]).state != "unavailable"

        # Simulate coordinator update failure
        mock_client.get_provisioning = AsyncMock(side_effect=TJA470Error("Device offline"))
        coordinator = entry.runtime_data.coordinator
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        # Entities should now be unavailable
        assert hass.states.get(camera_ids[0]).state == "unavailable"


async def test_snapshot_retention_cleanup(hass: HomeAssistant) -> None:
    """Test that expired snapshots are cleaned up correctly."""
    from datetime import datetime, timezone, timedelta
    import os
    from custom_components.tja470_intercom import (
        async_cleanup_expired_snapshots,
        async_get_call_history,
        async_save_call_history,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        options={"snapshot_retention_days": 3},
    )
    entry.add_to_hass(hass)

    # Mock snapshots directory and files
    snapshots_dir = os.path.join(hass.config.config_dir, ".storage", "tja470_snapshots")
    os.makedirs(snapshots_dir, exist_ok=True)

    # 1. Old call (5 days ago) with 1 snapshot
    old_call_time = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat().replace("+00:00", "Z")
    old_call_id = "11111111_old"
    old_file_path = os.path.join(snapshots_dir, f"snapshot_{old_call_id}_0.jpg")
    with open(old_file_path, "wb") as f:
        f.write(b"old_image")

    # 2. Recent call (1 day ago) with 1 snapshot
    recent_call_time = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    recent_call_id = "22222222_recent"
    recent_file_path = os.path.join(snapshots_dir, f"snapshot_{recent_call_id}_0.jpg")
    with open(recent_file_path, "wb") as f:
        f.write(b"recent_image")

    history = [
        {
            "id": old_call_id,
            "timestamp": old_call_time,
            "caller": "6001",
            "caller_name": "Old",
            "answered": True,
            "snapshots_count": 1,
        },
        {
            "id": recent_call_id,
            "timestamp": recent_call_time,
            "caller": "6002",
            "caller_name": "Recent",
            "answered": True,
            "snapshots_count": 1,
        }
    ]

    await async_save_call_history(hass, history)

    # Run cleanup
    await async_cleanup_expired_snapshots(hass, entry)

    # Verify old snapshot is deleted and history is updated
    assert not os.path.exists(old_file_path)
    # Verify recent snapshot is kept
    assert os.path.exists(recent_file_path)

    updated_history = await async_get_call_history(hass)
    assert updated_history[0]["snapshots_count"] == 0
    assert updated_history[1]["snapshots_count"] == 1

    # Cleanup recent file
    if os.path.exists(recent_file_path):
        os.remove(recent_file_path)




