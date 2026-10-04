"""Coordinator for Hager TJA470 Intercom."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.issue_registry import IssueSeverity, async_create_issue
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from aiotja470_intercom import TJA470IntercomClient
from aiotja470_intercom.exceptions import TJA470AuthError, TJA470Error
from aiotja470_intercom.models import ProvisioningInfo

from .const import CONF_COOKIES, CONF_KNOWN_VERSIONS, CONF_UUID, DOMAIN, LOGGER


class TJA470Coordinator(DataUpdateCoordinator[dict[str, Any]]):
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

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from TJA470 Intercom."""
        uuid_str = self.entry.data[CONF_UUID]
        try:
            provisioning_info = await self._async_get_provisioning(uuid_str)
            manifest = await self.client.get_manifest()
            try:
                software_version: str | None = await self.client.get_software_version()
            except TJA470Error as err:
                LOGGER.debug("Could not read the doorphone software version: %s", err)
                software_version = None
            self._async_check_versions(manifest.fw, software_version)

            updated_cookies = self.client.get_cookies()
            if updated_cookies != self.entry.data.get(CONF_COOKIES):
                LOGGER.debug("Saving updated cookies to config entry")
                new_data = {**self.entry.data, CONF_COOKIES: updated_cookies}
                self.hass.config_entries.async_update_entry(self.entry, data=new_data)

            try:
                sip_phone = self.entry.runtime_data.sip_phone
                sip_status = sip_phone.get_status().name
            except AttributeError:
                sip_status = "INACTIVE"

            return {
                "provisioning": provisioning_info,
                "manifest": manifest,
                "firmware_version": manifest.fw,
                "software_version": software_version,
                "sip_status": sip_status,
            }
        except TJA470AuthError as err:
            raise ConfigEntryAuthFailed("Authentication failed") from err
        except TJA470Error as err:
            raise UpdateFailed(f"Error communicating with TJA470: {err}") from err

    async def _async_get_provisioning(self, uuid_str: str) -> ProvisioningInfo:
        """Fetch provisioning, letting the device answer 304 if it is unchanged."""
        previous: ProvisioningInfo | None = (self.data or {}).get("provisioning")
        if previous is None or not previous.version:
            return await self.client.get_provisioning(uuid_str)
        changed = await self.client.get_provisioning_if_changed(uuid_str, previous.version)
        return previous if changed is None else changed

    def _async_check_versions(self, firmware: str | None, software: str | None) -> None:
        """Raise a repair issue when the device's firmware or software version changes.

        Updates restart the device, and after an automatic update the doorphone
        link to the 2-wire bus has been seen to stop working until the bus is
        power-cycled. The last seen versions are stored in the config entry so
        that updates while Home Assistant was not running are noticed too.
        """
        current = {"firmware": firmware, "software": software}
        known: dict[str, str | None] | None = self.entry.data.get(CONF_KNOWN_VERSIONS)
        if known == current:
            return
        changes = [
            f"{name} {known.get(name)} → {version}"
            for name, version in current.items()
            if known is not None
            and version is not None
            and known.get(name) is not None
            and known.get(name) != version
        ]
        if changes:
            LOGGER.warning("TJA470 at %s was updated: %s", self.entry.data[CONF_HOST], ", ".join(changes))
            async_create_issue(
                self.hass,
                DOMAIN,
                f"device_updated_{self.entry.entry_id}",
                is_fixable=True,
                severity=IssueSeverity.WARNING,
                translation_key="device_updated",
                translation_placeholders={
                    "host": self.entry.data[CONF_HOST],
                    "changes": ", ".join(changes),
                },
            )
        # Keep versions that could not be read this time.
        stored = {
            name: version if version is not None else (known or {}).get(name)
            for name, version in current.items()
        }
        if stored != known:
            self.hass.config_entries.async_update_entry(
                self.entry, data={**self.entry.data, CONF_KNOWN_VERSIONS: stored}
            )
