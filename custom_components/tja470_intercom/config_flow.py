"""Config flow for Hager TJA470 Intercom integration."""
from __future__ import annotations

import uuid
from typing import Any
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import config_validation as cv

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

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> TJA470OptionsFlowHandler:
        """Get the options flow for this handler."""
        return TJA470OptionsFlowHandler(config_entry)


class TJA470OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Hager TJA470 Intercom."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            if "notify_devices_text" in user_input:
                val = user_input.pop("notify_devices_text")
                user_input["notify_devices"] = [
                    x.strip() for x in val.split(",") if x.strip()
                ]
            return self.async_create_entry(title="", data=user_input)

        notify_services_set = set()
        if "notify" in self.hass.services.async_services():
            notify_services_set.update(self.hass.services.async_services()["notify"].keys())

        # Get all modern notify entities registered in the state machine
        notify_entities = self.hass.states.async_all("notify")
        for ne in notify_entities:
            notify_services_set.add(ne.entity_id)

        # Include currently configured notify devices so they don't get lost
        current_configured = self.config_entry.options.get("notify_devices", [])
        notify_services_set.update(current_configured)

        notify_services = sorted(list(notify_services_set))

        # Get device trackers and map them to our actual notify services/entities
        tracker_lines = []
        for service in notify_services:
            # Strip prefixes to get base name (e.g. notify.pixel_8 -> pixel_8, mobile_app_pixel_8 -> pixel_8)
            base_id = service
            if base_id.startswith("notify."):
                base_id = base_id[7:]
            if base_id.startswith("mobile_app_"):
                base_id = base_id[11:]

            tracker_state = self.hass.states.get(f"device_tracker.{base_id}")
            if tracker_state:
                name = tracker_state.attributes.get("friendly_name") or tracker_state.entity_id
                last_seen = getattr(tracker_state, "last_reported", None) or tracker_state.last_updated
                last_seen_str = last_seen.strftime("%Y-%m-%d %H:%M:%S") if last_seen else "unknown"
                tracker_lines.append(f"- {name} ({service}): last seen {last_seen_str}")

        schema = {}
        if notify_services:
            schema[
                vol.Optional(
                    "notify_devices",
                    default=self.config_entry.options.get("notify_devices", []),
                )
            ] = cv.multi_select({s: s for s in notify_services})
        else:
            schema[
                vol.Optional(
                    "notify_devices_text",
                    default=",".join(self.config_entry.options.get("notify_devices", [])),
                )
            ] = str


        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema),
            description_placeholders={
                "device_trackers": "\n".join(tracker_lines) if tracker_lines else "None found."
            },
        )
