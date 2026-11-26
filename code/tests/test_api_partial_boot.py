"""Partial boot failure must close acquired resources before reporting failure."""

import asyncio
import socket
from types import SimpleNamespace

import httpx
import pytest
from desk_robot.api_lifecycle import runtime_lifespan, runtime_ready
from starlette.datastructures import State


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_shutdown", [False, True])
async def test_partial_boot_failure_retires_worker_before_client(cancel_shutdown):
    state = State()
    failure = ValueError("partial boot failed")
    close_entered = asyncio.Event()
    worker_entered = asyncio.Event()
    client = httpx.AsyncClient(trust_env=False)
    left, right = socket.socketpair()
    calls = []
    worker = None

    async def run_worker():
        worker_entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            left.close()
            right.close()
            calls.append("worker closed")

    async def start():
        nonlocal worker
        worker = asyncio.create_task(run_worker())
        await worker_entered.wait()
        raise failure

    async def close():
        assert not runtime_ready(state)
        close_entered.set()
        try:
            if cancel_shutdown:
                await asyncio.Event().wait()
        finally:
            # Model Runtime.close's contract: finish owner cleanup before
            # propagating cancellation of the shutdown waiter.
            assert worker is not None
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
            assert worker.done()
            await client.aclose()
            calls.append("client closed")

    async def serve():
        async with runtime_lifespan(state):
            pytest.fail("A partially booted runtime must never serve")

    state.runtime = SimpleNamespace(start=start, close=close)
    task = asyncio.create_task(serve())
    try:
        await asyncio.wait_for(close_entered.wait(), timeout=1)
        if cancel_shutdown:
            task.cancel()
        with pytest.raises(ValueError, match="partial boot failed") as caught:
            await asyncio.wait_for(task, timeout=1)
        assert caught.value is failure
        assert not runtime_ready(state)
        assert calls == ["worker closed", "client closed"]
        assert worker is not None and worker.done()
        assert left.fileno() == right.fileno() == -1
        assert client.is_closed
        if cancel_shutdown:
            assert failure.__notes__ == ["Runtime shutdown also failed: CancelledError"]
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        if worker is not None and not worker.done():
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
        left.close()
        right.close()
        await client.aclose()


@pytest.mark.asyncio
async def test_shutdown_cancellation_without_boot_failure_propagates():
    state = State()
    close_entered = asyncio.Event()

    async def close():
        close_entered.set()
        await asyncio.Event().wait()

    async def serve():
        async with runtime_lifespan(state):
            assert runtime_ready(state)

    state.runtime = SimpleNamespace(close=close)
    task = asyncio.create_task(serve())
    try:
        await asyncio.wait_for(close_entered.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
        assert not runtime_ready(state)
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
