"""Shared room USB reader ownership on bounded runtime shutdown."""

import asyncio
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
        finally:
            release.set()
            await task

    asyncio.run(scenario())
