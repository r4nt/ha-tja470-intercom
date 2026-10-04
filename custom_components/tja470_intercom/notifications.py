"""Call notifications for Hager TJA470 Intercom."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import LOGGER


async def async_send_call_notifications(
    hass: HomeAssistant, entry: ConfigEntry, caller_name: str | None
) -> None:
    """Notify the configured devices about a doorbell call.

    caller_name is None when the call is known from the device's event bus,
    which does not say which door station is ringing.
    """
    notify_devices = entry.options.get("notify_devices", [])
    if not notify_devices:
        return
    message = (
        f"Incoming call from {caller_name}"
        if caller_name
        else "Someone is ringing at the door"
    )
    for device in notify_devices:
        service_name = device if not device.startswith("notify.") else device[7:]
        LOGGER.debug("Sending call notification via service notify.%s", service_name)
        try:
            await hass.services.async_call(
                "notify", service_name,
                {
                    "title": "Intercom Call",
                    "message": message,
                    "data": {
                        "ttl": 0,
                        "priority": "high",
                        "channel": "Intercom",
                        "clickAction": "/intercom",
                    },
                },
            )
        except Exception as err:
            LOGGER.error("Failed to send notification to %s: %s", device, err)
