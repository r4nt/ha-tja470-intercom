"""Event bus listener for Hager TJA470 Intercom."""
from __future__ import annotations

import asyncio
import time

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from aiotja470_intercom.exceptions import TJA470Error
from aiotja470_intercom.models import DoorphoneEvent

from .const import LOGGER
from .notifications import async_send_call_notifications

RECONNECT_DELAY_MIN = 5.0
RECONNECT_DELAY_MAX = 60.0


async def async_listen_for_events(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Listen to the device's event bus, reconnecting until cancelled.

    The event bus reports a doorbell ring (INCOMINGCALL) about 1.6 s before
    the SIP INVITE arrives, so notifications are sent from here.
    """
    client = entry.runtime_data.client
    delay = RECONNECT_DELAY_MIN
    while True:
        try:
            async for event in client.events():
                delay = RECONNECT_DELAY_MIN
                async_handle_event(hass, entry, event)
            LOGGER.debug("Event bus connection closed by the device")
        except (TJA470Error, aiohttp.ClientError, asyncio.TimeoutError) as err:
            LOGGER.debug("Event bus connection failed: %s", err)
        except Exception:
            LOGGER.exception("Unexpected error in the event bus listener")
        await asyncio.sleep(delay)
        delay = min(delay * 2, RECONNECT_DELAY_MAX)


def async_handle_event(hass: HomeAssistant, entry: ConfigEntry, event: DoorphoneEvent) -> None:
    """Handle one event from the device's event bus."""
    LOGGER.debug("Event: %s %s", event.name, event.value)
    if event.name.startswith("INCOMINGCALL/"):
        entry.runtime_data.ring_notified_at = time.monotonic()
        hass.async_create_task(async_send_call_notifications(hass, entry, None))
