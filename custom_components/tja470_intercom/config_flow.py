"""Config flow for Hager TJA470 Intercom integration."""
from __future__ import annotations

import uuid
from typing import Any
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from aiotja470_intercom import TJA470IntercomClient, AiohttpRunner
from aiotja470_intercom.exceptions import TJA470AuthError, TJA470ConnectionError, TJA470Error
from aiotja470_intercom.models import FreeDevice

from .const import CONF_COOKIES, CONF_UUID, DOMAIN, LOGGER


class TJA470ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hager TJA470 Intercom."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize flow."""
        self.host: str | None = None
        self.username: str | None = None
        self.password: str | None = None
        self.free_devices: list[FreeDevice] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self.host = user_input[CONF_HOST]
            self.username = user_input[CONF_USERNAME]
            self.password = user_input[CONF_PASSWORD]

            await self.async_set_unique_id(self.host)
            self._abort_if_unique_id_configured()

            # Validate connection and retrieve free devices
            session = async_get_clientsession(self.hass)
            runner = AiohttpRunner(session)
            client = TJA470IntercomClient(self.host, self.username, self.password, runner)

            try:
                # Test credentials by fetching manifest
                await client.get_manifest()
                # Get free devices for pairing
                self.free_devices = await client.get_free_devices()
            except TJA470AuthError:
                errors["base"] = "invalid_auth"
            except TJA470ConnectionError:
                errors["base"] = "cannot_connect"
            except TJA470Error as err:
                LOGGER.error("Unexpected error connecting to TJA470: %s", err)
                errors["base"] = "unknown"

            if not errors:
                if not self.free_devices:
                    return await self.async_step_no_devices()
                return await self.async_step_free_device()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def async_step_no_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle step when no free devices are available."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Retry fetching free devices
            session = async_get_clientsession(self.hass)
            runner = AiohttpRunner(session)
            client = TJA470IntercomClient(self.host, self.username, self.password, runner)

            try:
                self.free_devices = await client.get_free_devices()
            except TJA470AuthError:
                errors["base"] = "invalid_auth"
            except TJA470ConnectionError:
                errors["base"] = "cannot_connect"
            except TJA470Error as err:
                LOGGER.error("Unexpected error connecting to TJA470: %s", err)
                errors["base"] = "unknown"

            if not errors:
                if not self.free_devices:
                    # Still no free devices, show the step again with error/description
                    errors["base"] = "cannot_connect"
                else:
                    return await self.async_step_free_device()

        return self.async_show_form(
            step_id="no_devices",
            data_schema=vol.Schema({}),
            errors=errors,
        )

    async def async_step_free_device(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle pairing with a selected free device slot."""
        errors: dict[str, str] = {}

        if user_input is not None:
            device_id = user_input["device_id"]
            client_uuid = str(uuid.uuid4())

            session = async_get_clientsession(self.hass)
            runner = AiohttpRunner(session)
            client = TJA470IntercomClient(self.host, self.username, self.password, runner)

            try:
                # Pair the client UUID with the selected free slot
                await client.set_uid(device_id, client_uuid)
                # Verify provisioning works with the new UUID
                await client.get_provisioning(client_uuid)
            except TJA470AuthError:
                errors["base"] = "invalid_auth"
            except TJA470ConnectionError:
                errors["base"] = "cannot_connect"
            except TJA470Error as err:
                LOGGER.error("Unexpected error pairing with TJA470: %s", err)
                errors["base"] = "unknown"

            if not errors:
                return self.async_create_entry(
                    title=f"TJA470 Intercom ({self.host})",
                    data={
                        CONF_HOST: self.host,
                        CONF_USERNAME: self.username,
                        CONF_PASSWORD: self.password,
                        CONF_UUID: client_uuid,
                        CONF_COOKIES: client.get_cookies(),
                    },
                )

        device_options = {
            d.id: d.name or f"Slot {d.id} ({d.mac or 'Unknown MAC'})"
            for d in self.free_devices
        }

        return self.async_show_form(
            step_id="free_device",
            data_schema=vol.Schema(
                {
                    vol.Required("device_id"): vol.In(device_options),
                }
            ),
            errors=errors,
        )
