"""Tests for the event bus listener."""
import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant, ServiceCall, callback
from pytest_homeassistant_custom_component.common import MockConfigEntry

from aiotja470_intercom.exceptions import TJA470ConnectionError
from aiotja470_intercom.models import DoorphoneEvent

from custom_components.tja470_intercom.const import DOMAIN
from custom_components.tja470_intercom.events import async_handle_event, async_listen_for_events

PREFIX = "com/hager/doorphone/runtime/rest/"


def make_entry(hass: HomeAssistant, client=None) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={"notify_devices": ["mobile_app_phone1"]})
    entry.add_to_hass(hass)
    entry.runtime_data = SimpleNamespace(client=client, ring_notified_at=None)
    return entry


def record_notifications(hass: HomeAssistant) -> list[ServiceCall]:
    calls: list[ServiceCall] = []

    @callback
    def record(call: ServiceCall) -> None:
        calls.append(call)

    hass.services.async_register("notify", "mobile_app_phone1", record)
    return calls


async def events_from(*events):
    for event in events:
        yield event


async def test_incoming_call_event_notifies(hass: HomeAssistant) -> None:
    entry = make_entry(hass)
    calls = record_notifications(hass)

    async_handle_event(hass, entry, DoorphoneEvent(topic=PREFIX + "INCOMINGCALL/1"))
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert calls[0].data["message"] == "Someone is ringing at the door"
    assert entry.runtime_data.ring_notified_at is not None


async def test_other_events_do_not_notify(hass: HomeAssistant) -> None:
    entry = make_entry(hass)
    calls = record_notifications(hass)

    async_handle_event(hass, entry, DoorphoneEvent(topic=PREFIX + "currentDevice/UPDATED", value={"order": 1}))
    async_handle_event(hass, entry, DoorphoneEvent(topic=PREFIX + "callhistory/CREATED/1"))
    await hass.async_block_till_done()

    assert calls == []
    assert entry.runtime_data.ring_notified_at is None


async def test_listener_reconnects_after_error(hass: HomeAssistant) -> None:
    client = MagicMock()
    client.events = MagicMock(side_effect=[
        TJA470ConnectionError("down"),
        events_from(DoorphoneEvent(topic=PREFIX + "INCOMINGCALL/1")),
    ])
    entry = make_entry(hass, client)
    calls = record_notifications(hass)

    sleep = AsyncMock(side_effect=[None, asyncio.CancelledError()])
    with patch("custom_components.tja470_intercom.events.asyncio.sleep", sleep):
        with pytest.raises(asyncio.CancelledError):
            await async_listen_for_events(hass, entry)
    await hass.async_block_till_done()

    assert client.events.call_count == 2
    assert len(calls) == 1
    # Backoff after the error, reset after a successful connection.
    assert [c.args[0] for c in sleep.await_args_list] == [5.0, 5.0]
