"""Tests for the Hager TJA470 Intercom platforms (button, camera, sensor)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from homeassistant.components.button import SERVICE_PRESS
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tja470_intercom.const import CONF_UUID, DOMAIN
from aiotja470_intercom.models import ProvisioningInfo, Manifest, SipInfo, CalledElement

pytestmark = pytest.mark.asyncio


async def test_platforms(hass: HomeAssistant) -> None:
    """Test setup and actions for button, camera, and sensor entities."""
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
            rtsp_video_url="rtsp://${ipadress}:9099/high",
            called_elements=[
                CalledElement(sip_id="4000", name="Driveway", order=0),
            ],
        )
    )
    mock_client.open_door = AsyncMock()
    mock_client.open_door_at_position = AsyncMock()
    mock_client.get_cookies = MagicMock(return_value={})

    with patch(
        "custom_components.tja470_intercom.TJA470IntercomClient",
        return_value=mock_client,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Find entity IDs dynamically to prevent HA naming version issues
        states = {state.entity_id: state for state in hass.states.async_all()}
        
        # Verify Button platforms
        open_active_btn = next((eid for eid in states if eid.endswith("open_active_door")), None)
        assert open_active_btn is not None

        open_driveway_btn = next((eid for eid in states if eid.endswith("driveway_open")), None)
        assert open_driveway_btn is not None

        # Verify Camera platform
        camera_eid = next((eid for eid in states if eid.startswith("camera.")), None)
        assert camera_eid is not None

        camera_entity = hass.data["entity_components"]["camera"].get_entity(camera_eid)
        assert camera_entity is not None

        with patch("custom_components.tja470_intercom.camera.async_get_image") as mock_get_image:
            # Case 1: FFmpeg returns valid JPEG bytes
            mock_get_image.return_value = b"jpeg_bytes"
            assert await camera_entity.async_camera_image() == b"jpeg_bytes"

            # Case 2: FFmpeg returns empty bytes (timeout/offline)
            mock_get_image.return_value = b""
            assert await camera_entity.async_camera_image() is None

            # Case 3: FFmpeg returns None (error/timeout)
            mock_get_image.return_value = None
            assert await camera_entity.async_camera_image() is None

        # Verify Sensor platform
        sip_username_eid = next((eid for eid in states if eid.endswith("sip_username")), None)
        assert sip_username_eid is None

        sip_password_eid = next((eid for eid in states if eid.endswith("sip_password")), None)
        assert sip_password_eid is None

        rtsp_url_eid = next((eid for eid in states if eid.endswith("rtsp_stream_url")), None)
        assert rtsp_url_eid is not None
        assert states[rtsp_url_eid].state == "rtsp://192.168.42.2:9099/high"

        # Action: Press the Active Door Release button
        await hass.services.async_call(
            "button",
            SERVICE_PRESS,
            {ATTR_ENTITY_ID: open_active_btn},
            blocking=True,
        )
        mock_client.open_door.assert_called_once_with(door_id=1)

        # Action: Press the specific Door Release button (Driveway)
        await hass.services.async_call(
            "button",
            SERVICE_PRESS,
            {ATTR_ENTITY_ID: open_driveway_btn},
            blocking=True,
        )
        mock_client.open_door_at_position.assert_called_once_with(
            "some-uuid", 0, door_id=1
        )
