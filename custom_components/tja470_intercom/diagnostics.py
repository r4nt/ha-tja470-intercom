"""Diagnostics for Hager TJA470 Intercom."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

TO_REDACT = {"password", "sip_password", "cookies", "JSESSIONID", "stun_password"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data.coordinator

    coord_data: dict[str, Any] = {}
    if coordinator.data:
        prov = coordinator.data.get("provisioning")
        manifest = coordinator.data.get("manifest")
        coord_data = {
            "sip_status": coordinator.data.get("sip_status"),
            "firmware": manifest.fw if manifest else None,
            "provisioning": async_redact_data(
                {
                    "sip_id": prov.sip_info.sip_id if prov else None,
                    "sip_password": prov.sip_info.sip_password if prov else None,
                    "rtsp_video_url": prov.rtsp_video_url if prov else None,
                    "local_ip_address": prov.local_ip_address if prov else None,
                    "door_release_allowed": prov.door_release_allowed if prov else None,
                    "called_elements": [
                        {"sip_id": e.sip_id, "name": e.name, "order": e.order}
                        for e in (prov.called_elements if prov else [])
                    ],
                },
                TO_REDACT,
            ),
        }

    return {
        "entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "coordinator": coord_data,
        "active_call": entry.runtime_data.active_call is not None,
    }
