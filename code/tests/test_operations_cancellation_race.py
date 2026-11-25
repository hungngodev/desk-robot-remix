"""Regression tests for bounded transport task exception ownership."""

import asyncio
import gc

import pytest

from desk_robot.operations import _bounded_head_reply


@pytest.mark.asyncio
async def test_parent_cancelled_by_failing_child_observes_child_exception():
    loop = asyncio.get_running_loop()
    original_handler = loop.get_exception_handler()
    unhandled = []
    loop.set_exception_handler(lambda _loop, context: unhandled.append(context))

    async def fail():
        parent.cancel()
        raise RuntimeError("transport failed concurrently with cancellation")

    try:
        parent = asyncio.create_task(
            _bounded_head_reply(fail(), seconds=1, timeout_message="timeout")
        )
        with pytest.raises(asyncio.CancelledError):
            await parent
        del parent
        gc.collect()
        await asyncio.sleep(0)
        assert not unhandled
    finally:
        loop.set_exception_handler(original_handler)


@pytest.mark.asyncio
async def test_child_exception_propagates():
    async def fail():
        raise RuntimeError("transport failed")

    with pytest.raises(RuntimeError, match="transport failed"):
        await _bounded_head_reply(fail(), seconds=1, timeout_message="timeout")


@pytest.mark.asyncio
async def test_late_result_not_accepted():
    release = asyncio.Event()
    finished = asyncio.Event()

    async def stubborn():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release.wait()
        finally:
            finished.set()
        return {"ok": True}

    try:
        with pytest.raises(TimeoutError, match="timeout"):
            await _bounded_head_reply(stubborn(), seconds=0.01, timeout_message="timeout")
    finally:
        release.set()
        await asyncio.wait_for(finished.wait(), 1)
