"""Unit tests for the async event bus."""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.events import Event, EventBus, EventType


@pytest.fixture
def bus():
    return EventBus()


def test_subscribe_and_publish(bus):
    seen = []

    async def handler(event):
        seen.append(event)

    async def run():
        bus.subscribe(EventType.ORDER_FILLED, handler)
        await bus.publish(Event(type=EventType.ORDER_FILLED, payload={"x": 1}))

    asyncio.run(run())
    assert len(seen) == 1
    assert seen[0].type == EventType.ORDER_FILLED


def test_wildcard_subscription(bus):
    seen = []

    async def handler(event):
        seen.append(event.type)

    async def run():
        bus.subscribe_all(handler)
        await bus.publish(Event(type=EventType.SYSTEM_STARTUP))

    asyncio.run(run())
    assert EventType.SYSTEM_STARTUP in seen


def test_handler_exception_does_not_break_publish(bus):
    seen = []

    def bad_handler(event):
        raise RuntimeError("boom")

    async def good(event):
        seen.append(event)

    async def run():
        bus.subscribe(EventType.ERROR_DETECTED, bad_handler)
        bus.subscribe(EventType.ERROR_DETECTED, good)
        await bus.publish(Event(type=EventType.ERROR_DETECTED))

    asyncio.run(run())
    assert len(seen) == 1


def test_event_has_unique_ids_and_timestamp():
    import time as t

    e1 = Event(type=EventType.ORDER_SUBMITTED)
    e2 = Event(type=EventType.ORDER_SUBMITTED)
    assert e1.event_id != e2.event_id
    assert abs(e1.timestamp - t.time()) < 5.0
