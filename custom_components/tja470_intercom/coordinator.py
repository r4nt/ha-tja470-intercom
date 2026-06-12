"""Coordinator for Hager TJA470 Intercom."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from aiotja470_intercom import TJA470IntercomClient
from aiotja470_intercom.exceptions import TJA470AuthError, TJA470Error

from .const import CONF_COOKIES, CONF_UUID, DOMAIN, LOGGER


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
                "sip_status": sip_status,
            }
        except TJA470AuthError as err:
            raise ConfigEntryAuthFailed("Authentication failed") from err
        except TJA470Error as err:
            raise UpdateFailed(f"Error communicating with TJA470: {err}") from err
