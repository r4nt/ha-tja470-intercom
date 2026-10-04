"""Repairs for Hager TJA470 Intercom."""
from __future__ import annotations

from typing import Any

from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.core import HomeAssistant


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, Any] | None,
) -> RepairsFlow:
    """Create a flow to confirm a repair issue.

    The only fixable issue is the device update notice, which the user
    confirms after checking that the doorbell and camera still work.
    """
    return ConfirmRepairFlow()
