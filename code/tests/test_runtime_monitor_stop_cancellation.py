"""Cancellation at the native STOP deadline must still observe child failures."""

import asyncio
import gc
from functools import partial

import pytest
from desk_robot.api import _bounded_cleanup
from desk_robot.runtime import _bounded_monitor_stop


@pytest.fixture(params=["runtime", "api"])
def stop(request):
    if request.param == "runtime":
        return _bounded_monitor_stop
    return partial(_bounded_cleanup, seconds=1, message="STOP unconfirmed")


@pytest.mark.asyncio
async def test_monitor_stop_observes_failure_during_parent_cancellation(stop):
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()
    unhandled = []
    loop.set_exception_handler(lambda _loop, context: unhandled.append(context))

    async def fail():
        parent.cancel()
        raise RuntimeError("decoder STOP failed while caller was cancelled")

    try:
        parent = asyncio.create_task(stop(fail()))
        with pytest.raises(asyncio.CancelledError):
            await parent
        parent = None
        gc.collect()
        await asyncio.sleep(0)
        assert not unhandled
    finally:
        loop.set_exception_handler(previous_handler)


@pytest.mark.asyncio
async def test_monitor_stop_propagates_decoder_failure(stop):
    async def fail():
        raise RuntimeError("decoder STOP failed")

    with pytest.raises(RuntimeError, match="decoder STOP failed"):
        await stop(fail())
