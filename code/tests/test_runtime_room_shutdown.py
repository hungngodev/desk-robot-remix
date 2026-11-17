"""Shared room USB reader ownership on bounded runtime shutdown."""

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from desk_robot.runtime import Runtime


def test_room_shutdown_timeout_keeps_live_reader_owned():
    async def scenario():
        release = asyncio.Event()
        entered = asyncio.Event()

        async def stalled_reader():
            entered.set()
            await release.wait()

        runtime = Runtime.__new__(Runtime)
        runtime.settings = SimpleNamespace(mode="simulation")
        runtime.coordinator = SimpleNamespace(
            close=AsyncMock(), shutdown_stop_failures={}
        )
        runtime.pet = SimpleNamespace(close=AsyncMock())
        runtime.conversation = SimpleNamespace(stop=AsyncMock())
        runtime.client = SimpleNamespace(aclose=AsyncMock())
        runtime.multimodal = None
        runtime._voice_task = None
        runtime._room_stop = asyncio.Event()
        runtime._room_dispatch_lock = threading.Lock()
        runtime._room_dispatch_pending = None
        runtime._room_dispatch_enqueued = False
        task = asyncio.create_task(stalled_reader())
        runtime._room_task = task
        await entered.wait()
        try:
            with pytest.raises(TimeoutError, match="Shared room USB shutdown unconfirmed"):
                await runtime.close()
            assert runtime._closed
            assert runtime._room_stop.is_set()
            assert runtime._room_task is task
            assert not task.done()
            assert task.cancelling() == 0  # timeout must not cancel reader
        finally:
            release.set()
            await task

    asyncio.run(scenario())


def test_cancelled_reader_keeps_cleanup_order_and_reports_unconfirmed_stop():
    """An independently cancelled USB task must not skip final other owners."""
    async def scenario():
        runtime = Runtime.__new__(Runtime)
        runtime.settings = SimpleNamespace(mode="simulation")
        runtime.coordinator = SimpleNamespace(
            close=AsyncMock(), shutdown_stop_failures={}
        )
        runtime.pet = SimpleNamespace(close=AsyncMock())
        runtime.conversation = SimpleNamespace(stop=AsyncMock())
        runtime.client = SimpleNamespace(aclose=AsyncMock())
        runtime.multimodal = None
        runtime._voice_task = None
        runtime._room_stop = asyncio.Event()
        runtime._room_dispatch_lock = threading.Lock()
        runtime._room_dispatch_pending = None
        runtime._room_dispatch_enqueued = False
        task = asyncio.create_task(asyncio.sleep(60))
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        runtime._room_task = task

        with pytest.raises(
            RuntimeError,
            match="Shared room USB shutdown task cancelled without confirmation",
        ):
            await runtime.close()

        assert runtime._room_stop.is_set()
        assert runtime._room_task is None
        runtime.coordinator.close.assert_awaited_once()
        runtime.pet.close.assert_awaited_once()
        runtime.conversation.stop.assert_awaited_once()
        runtime.client.aclose.assert_awaited_once()

    asyncio.run(scenario())
