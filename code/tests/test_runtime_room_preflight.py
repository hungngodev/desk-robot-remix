"""Reject invalid room prerequisites before opening consented camera transport."""

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from desk_robot.runtime import Runtime


def runtime_with_room():
    runtime = Runtime.__new__(Runtime)
    runtime.settings = SimpleNamespace(
        mode="hardware",
        robots=[],
        room_station_enabled=True,
        room_station_soil_dry_adc=3000,
        room_station_soil_wet_adc=1000,
        room_station_port="/dev/ttyUSB0",
    )
    runtime._closed = False
    runtime._voice_task = None
    runtime._room_task = None
    runtime._room_stop = asyncio.Event()
    runtime._on_room_disconnect = Mock()
    runtime._on_service_done = Mock()
    runtime.multimodal = SimpleNamespace(start_streams=Mock())
    runtime.room_feed = None
    return runtime


@pytest.mark.parametrize("failure", ["missing_serial", "invalid_soil", "invalid_port"])
async def test_room_preflight_failure_never_starts_camera(monkeypatch, failure):
    runtime = runtime_with_room()
    monkeypatch.setitem(sys.modules, "serial", None if failure == "missing_serial" else Mock())
    factory = Mock()
    monkeypatch.setattr("desk_robot.runtime.RoomSerialFeed", factory)
    error = RuntimeError if failure == "missing_serial" else ValueError
    if failure == "invalid_soil":
        runtime.settings.room_station_soil_wet_adc = 3000
    if failure == "invalid_port":
        factory.side_effect = ValueError("Room station requires an explicit local serial device")

    with pytest.raises(error):
        await runtime.start()

    runtime.multimodal.start_streams.assert_not_called()
    assert runtime._room_task is None
    assert runtime.room_feed is None
    if failure != "invalid_port":
        factory.assert_not_called()


@pytest.mark.parametrize("enabled", [False, True])
async def test_valid_room_preflight_preserves_camera_and_reader(monkeypatch, enabled):
    runtime = runtime_with_room()
    runtime.settings.room_station_enabled = enabled
    monkeypatch.setitem(sys.modules, "serial", Mock() if enabled else None)
    feed = SimpleNamespace(run=AsyncMock())
    factory = Mock(return_value=feed)
    monkeypatch.setattr("desk_robot.runtime.RoomSerialFeed", factory)
    order = Mock()
    order.attach_mock(factory, "room")
    order.attach_mock(runtime.multimodal.start_streams, "camera")

    await runtime.start()

    runtime.multimodal.start_streams.assert_called_once_with()
    if enabled:
        assert [call[0] for call in order.mock_calls] == ["room", "camera"]
        assert runtime.room_feed is feed
        await runtime._room_task
        feed.run.assert_awaited_once_with(runtime._room_stop)
    else:
        factory.assert_not_called()
        assert runtime._room_task is None
        assert runtime.room_feed is None


async def test_camera_start_failure_does_not_launch_room_reader(monkeypatch):
    runtime = runtime_with_room()
    monkeypatch.setitem(sys.modules, "serial", Mock())
    feed = SimpleNamespace(run=AsyncMock())
    factory = Mock(return_value=feed)
    monkeypatch.setattr("desk_robot.runtime.RoomSerialFeed", factory)
    runtime.multimodal.start_streams.side_effect = OSError("camera unavailable")

    with pytest.raises(OSError, match="camera unavailable"):
        await runtime.start()

    factory.assert_called_once()
    feed.run.assert_not_called()
    assert runtime._room_task is None
    assert runtime.room_feed is None
