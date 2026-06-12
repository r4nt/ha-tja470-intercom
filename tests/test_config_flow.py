"""Tests for the Hager TJA470 Intercom config flow."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from homeassistant import config_entries, data_entry_flow
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tja470_intercom.const import CONF_COOKIES, CONF_UUID, DOMAIN
from aiotja470_intercom.exceptions import TJA470AuthError, TJA470ConnectionError, TJA470Error
from aiotja470_intercom.models import FreeDevice, Manifest, ProvisioningInfo, SipInfo

pytestmark = pytest.mark.asyncio


async def test_flow_success(hass: HomeAssistant) -> None:
    """Test successful configuration flow pairing."""
    mock_client = MagicMock()
    
    # We use AsyncMocks for coroutines
    mock_client.get_manifest = AsyncMock(return_value=Manifest(raw_data={"fw": "2.7.3"}))
    mock_client.get_free_devices = AsyncMock(
        return_value=[FreeDevice(id=1, name="Slot 1", mac="AA:BB:CC:DD:EE:FF")]
    )
    mock_client.set_uid = AsyncMock()
    mock_client.get_cookies = MagicMock(return_value={"JSESSIONID": "somecookie"})
    mock_client.get_provisioning = AsyncMock(
        return_value=ProvisioningInfo(
            sip_info=SipInfo(sip_id="6004", sip_password="pwd"),
            rtsp_video_url="rtsp://some_url",
            http_video_url="http://some_http_url",
            local_ip_address="192.168.42.2",
            door_release_allowed=True,
        )
    )

    with patch(
        "custom_components.tja470_intercom.config_flow.TJA470IntercomClient",
        return_value=mock_client,
    ), patch(
        "custom_components.tja470_intercom.async_setup_entry",
        return_value=True,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "user"

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_HOST: "192.168.42.2",
                CONF_USERNAME: "manuel",
                CONF_PASSWORD: "pwd",
            },
        )
        assert result2["type"] == data_entry_flow.FlowResultType.FORM
        assert result2["step_id"] == "free_device"

        result3 = await hass.config_entries.flow.async_configure(
            result2["flow_id"],
            {
                "device_id": 1,
            },
        )
        assert result3["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
        assert result3["title"] == "TJA470 Intercom (192.168.42.2)"
        assert result3["data"][CONF_HOST] == "192.168.42.2"
        assert result3["data"][CONF_USERNAME] == "manuel"
        assert result3["data"][CONF_PASSWORD] == "pwd"
        assert CONF_UUID in result3["data"]
        assert result3["data"][CONF_COOKIES] == {"JSESSIONID": "somecookie"}


async def test_flow_no_devices_initially(hass: HomeAssistant) -> None:
    """Test flow when no free device slots are initially available, and user retries."""
    mock_client = MagicMock()
    
    mock_client.get_manifest = AsyncMock(return_value=Manifest(raw_data={"fw": "2.7.3"}))
    # First time returns empty list, second time returns device slot
    mock_client.get_free_devices = AsyncMock()
    mock_client.get_free_devices.side_effect = [
        [],
        [FreeDevice(id=1, name="Slot 1")],
    ]
    mock_client.set_uid = AsyncMock()
    mock_client.get_cookies = MagicMock(return_value={})
    mock_client.get_provisioning = AsyncMock(
        return_value=ProvisioningInfo(
            sip_info=SipInfo(sip_id="6004", sip_password="pwd"),
            rtsp_video_url="rtsp://some_url",
            http_video_url="http://some_http_url",
            local_ip_address="192.168.42.2",
            door_release_allowed=True,
        )
    )

    with patch(
        "custom_components.tja470_intercom.config_flow.TJA470IntercomClient",
        return_value=mock_client,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_HOST: "192.168.42.2",
                CONF_USERNAME: "manuel",
                CONF_PASSWORD: "pwd",
            },
        )
        # Should route to no_devices warning step
        assert result2["type"] == data_entry_flow.FlowResultType.FORM
        assert result2["step_id"] == "no_devices"

        # Retry setup (user clicks next after freeing slot)
        result3 = await hass.config_entries.flow.async_configure(
            result2["flow_id"],
            {},
        )
        assert result3["type"] == data_entry_flow.FlowResultType.FORM
        assert result3["step_id"] == "free_device"


async def test_flow_auth_failure(hass: HomeAssistant) -> None:
    """Test login validation failing with bad credentials."""
    mock_client = MagicMock()
    mock_client.get_manifest = AsyncMock(side_effect=TJA470AuthError("Auth failed"))

    with patch(
        "custom_components.tja470_intercom.config_flow.TJA470IntercomClient",
        return_value=mock_client,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_HOST: "192.168.42.2",
                CONF_USERNAME: "manuel",
                CONF_PASSWORD: "pwd",
            },
        )
        assert result2["type"] == data_entry_flow.FlowResultType.FORM
        assert result2["errors"] == {"base": "invalid_auth"}


async def test_flow_cannot_connect(hass: HomeAssistant) -> None:
    """Test flow handling connection error."""
    mock_client = MagicMock()
    mock_client.get_manifest = AsyncMock(side_effect=TJA470ConnectionError("Conn failed"))

    with patch(
        "custom_components.tja470_intercom.config_flow.TJA470IntercomClient",
        return_value=mock_client,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_HOST: "192.168.42.2",
                CONF_USERNAME: "manuel",
                CONF_PASSWORD: "pwd",
            },
        )
        assert result2["type"] == data_entry_flow.FlowResultType.FORM
        assert result2["errors"] == {"base": "cannot_connect"}


async def test_flow_free_device_pairing_error(hass: HomeAssistant) -> None:
    """Test error shown when pairing in async_step_free_device fails."""
    mock_client = MagicMock()
    mock_client.get_manifest = AsyncMock(return_value=Manifest(raw_data={"fw": "2.7.3"}))
    mock_client.get_free_devices = AsyncMock(
        return_value=[FreeDevice(id=1, name="Slot 1", mac="AA:BB:CC:DD:EE:FF")]
    )
    mock_client.set_uid = AsyncMock(side_effect=TJA470Error("Pairing failed"))
    mock_client.get_cookies = MagicMock(return_value={})

    with patch(
        "custom_components.tja470_intercom.config_flow.TJA470IntercomClient",
        return_value=mock_client,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: "192.168.42.2", CONF_USERNAME: "manuel", CONF_PASSWORD: "pwd"},
        )
        assert result2["step_id"] == "free_device"

        result3 = await hass.config_entries.flow.async_configure(
            result2["flow_id"],
            {"device_id": 1},
        )
        assert result3["type"] == data_entry_flow.FlowResultType.FORM
        assert result3["step_id"] == "free_device"
        assert result3["errors"] == {"base": "unknown"}


async def test_flow_no_devices_still_no_devices(hass: HomeAssistant) -> None:
    """Test that retrying no_devices step shows error when still no slots available."""
    mock_client = MagicMock()
    mock_client.get_manifest = AsyncMock(return_value=Manifest(raw_data={"fw": "2.7.3"}))
    mock_client.get_free_devices = AsyncMock(return_value=[])
    mock_client.get_cookies = MagicMock(return_value={})

    with patch(
        "custom_components.tja470_intercom.config_flow.TJA470IntercomClient",
        return_value=mock_client,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: "192.168.42.2", CONF_USERNAME: "manuel", CONF_PASSWORD: "pwd"},
        )
        assert result2["step_id"] == "no_devices"

        # Retry but still no devices available
        result3 = await hass.config_entries.flow.async_configure(
            result2["flow_id"],
            {},
        )
        assert result3["type"] == data_entry_flow.FlowResultType.FORM
        assert result3["step_id"] == "no_devices"
        assert result3["errors"] == {"base": "cannot_connect"}


async def test_reauth_flow_success(hass: HomeAssistant) -> None:
    """Test successful reauthentication updates credentials and reloads entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_HOST: "192.168.42.2",
            CONF_USERNAME: "old_user",
            CONF_PASSWORD: "old_pwd",
            "uuid": "some-uuid",
        },
    )
    entry.add_to_hass(hass)

    mock_client = MagicMock()
    mock_client.get_manifest = AsyncMock(return_value=None)

    with patch(
        "custom_components.tja470_intercom.config_flow.TJA470IntercomClient",
        return_value=mock_client,
    ), patch(
        "custom_components.tja470_intercom.async_setup_entry",
        return_value=True,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
            data=entry.data,
        )
        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "reauth_confirm"

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "new_user", CONF_PASSWORD: "new_pwd"},
        )
        assert result2["type"] == data_entry_flow.FlowResultType.ABORT
        assert result2["reason"] == "reauth_successful"

    assert entry.data[CONF_USERNAME] == "new_user"
    assert entry.data[CONF_PASSWORD] == "new_pwd"


async def test_reauth_flow_invalid_auth(hass: HomeAssistant) -> None:
    """Test reauthentication shows error on bad credentials."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_HOST: "192.168.42.2",
            CONF_USERNAME: "old_user",
            CONF_PASSWORD: "old_pwd",
            "uuid": "some-uuid",
        },
    )
    entry.add_to_hass(hass)

    mock_client = MagicMock()
    mock_client.get_manifest = AsyncMock(side_effect=TJA470AuthError("Bad credentials"))

    with patch(
        "custom_components.tja470_intercom.config_flow.TJA470IntercomClient",
        return_value=mock_client,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
            data=entry.data,
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "bad_user", CONF_PASSWORD: "bad_pwd"},
        )
        assert result2["type"] == data_entry_flow.FlowResultType.FORM
        assert result2["step_id"] == "reauth_confirm"
        assert result2["errors"] == {"base": "invalid_auth"}
