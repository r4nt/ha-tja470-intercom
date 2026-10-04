"""Tests for the TJA470 coordinator."""
from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.repairs import ConfirmRepairFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from aiotja470_intercom.models import Manifest, ProvisioningInfo, SipInfo

from custom_components.tja470_intercom.const import CONF_KNOWN_VERSIONS, CONF_UUID, DOMAIN
from custom_components.tja470_intercom.coordinator import TJA470Coordinator
from custom_components.tja470_intercom.repairs import async_create_fix_flow


def make_provisioning(version: str | None = None) -> ProvisioningInfo:
    return ProvisioningInfo(
        sip_info=SipInfo(sip_id="6014", sip_password="pwd"),
        rtsp_video_url="rtsp://some_url",
        http_video_url="http://some_http_url",
        local_ip_address="192.168.42.2",
        door_release_allowed=True,
        version=version,
    )


def make_coordinator(hass: HomeAssistant, data: dict | None = None):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "host": "192.168.42.2",
            "username": "manuel",
            "password": "pwd",
            CONF_UUID: "some-uuid",
            **(data or {}),
        },
    )
    entry.add_to_hass(hass)
    client = MagicMock()
    client.get_provisioning = AsyncMock(return_value=make_provisioning("v1"))
    client.get_provisioning_if_changed = AsyncMock(return_value=None)
    client.get_manifest = AsyncMock(return_value=Manifest(raw_data={"fw": "2.7.3"}))
    client.get_software_version = AsyncMock(return_value="4.0.2")
    client.get_cookies = MagicMock(return_value={})
    return TJA470Coordinator(hass, client, entry), client, entry


def update_issue(hass: HomeAssistant, entry) -> ir.IssueEntry | None:
    return ir.async_get(hass).async_get_issue(DOMAIN, f"device_updated_{entry.entry_id}")


async def test_first_poll_stores_versions_without_issue(hass: HomeAssistant) -> None:
    coordinator, _, entry = make_coordinator(hass)

    data = await coordinator._async_update_data()

    assert data["firmware_version"] == "2.7.3"
    assert data["software_version"] == "4.0.2"
    assert entry.data[CONF_KNOWN_VERSIONS] == {"firmware": "2.7.3", "software": "4.0.2"}
    assert update_issue(hass, entry) is None


async def test_version_change_raises_issue(hass: HomeAssistant) -> None:
    coordinator, client, entry = make_coordinator(
        hass, {CONF_KNOWN_VERSIONS: {"firmware": "2.7.2", "software": "4.0.2"}}
    )

    await coordinator._async_update_data()

    issue = update_issue(hass, entry)
    assert issue is not None
    assert issue.is_fixable
    assert issue.translation_key == "device_updated"
    assert issue.translation_placeholders["changes"] == "firmware 2.7.2 → 2.7.3"
    assert entry.data[CONF_KNOWN_VERSIONS] == {"firmware": "2.7.3", "software": "4.0.2"}


async def test_unchanged_versions_raise_no_issue(hass: HomeAssistant) -> None:
    coordinator, _, entry = make_coordinator(
        hass, {CONF_KNOWN_VERSIONS: {"firmware": "2.7.3", "software": "4.0.2"}}
    )

    await coordinator._async_update_data()

    assert update_issue(hass, entry) is None


async def test_unreadable_software_version_keeps_known_version(hass: HomeAssistant) -> None:
    from aiotja470_intercom.exceptions import TJA470ResponseError

    coordinator, client, entry = make_coordinator(
        hass, {CONF_KNOWN_VERSIONS: {"firmware": "2.7.3", "software": "4.0.2"}}
    )
    client.get_software_version = AsyncMock(side_effect=TJA470ResponseError("boom"))

    data = await coordinator._async_update_data()

    assert data["software_version"] is None
    assert entry.data[CONF_KNOWN_VERSIONS] == {"firmware": "2.7.3", "software": "4.0.2"}
    assert update_issue(hass, entry) is None


async def test_provisioning_uses_version_after_first_poll(hass: HomeAssistant) -> None:
    coordinator, client, _ = make_coordinator(hass)

    coordinator.data = await coordinator._async_update_data()
    client.get_provisioning.assert_awaited_once_with("some-uuid")

    data = await coordinator._async_update_data()
    client.get_provisioning_if_changed.assert_awaited_once_with("some-uuid", "v1")
    assert data["provisioning"] is coordinator.data["provisioning"]

    changed = make_provisioning("v2")
    client.get_provisioning_if_changed = AsyncMock(return_value=changed)
    data = await coordinator._async_update_data()
    assert data["provisioning"] is changed


async def test_repair_flow_is_confirm_flow(hass: HomeAssistant) -> None:
    flow = await async_create_fix_flow(hass, "device_updated_x", None)
    assert isinstance(flow, ConfirmRepairFlow)
