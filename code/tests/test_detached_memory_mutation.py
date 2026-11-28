"""Detached operator memory writes must report failure without private details."""

import asyncio
from threading import Event
from types import SimpleNamespace

import pytest
from desk_robot.api_memory_routes import _create_memory_mutation_runner, _logger


@pytest.mark.asyncio
async def test_detached_mutation_failure_is_reported_without_private_detail(monkeypatch):
    runner = _create_memory_mutation_runner(
        SimpleNamespace(robots=[SimpleNamespace(id="robot-01")]),
    )
    entered, release = Event(), Event()
    reported = asyncio.Event()
    messages = []

    def warning(message):
        messages.append(message)
        reported.set()

    monkeypatch.setattr(_logger, "warning", warning)

    def mutate(robot_id, *, mutation_generation):
        entered.set()
        assert release.wait(2)
        raise RuntimeError("private backend diagnostic: /local/pet.db")

    invalidated = []
    request = asyncio.create_task(runner(
        lambda robot_id: 1, mutate, "robot-01",
        invalidate=lambda: invalidated.append(True),
    ))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
        release.set()
        await asyncio.wait_for(reported.wait(), timeout=1)
        assert messages == ["Detached operator memory mutation failed"]
        assert invalidated == []
    finally:
        release.set()
        if not request.done():
            request.cancel()
            await asyncio.gather(request, return_exceptions=True)
