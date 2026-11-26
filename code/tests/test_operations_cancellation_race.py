"""Regression tests for bounded transport task exception ownership."""

import asyncio
import gc

import pytest
from desk_robot.operations import _bounded_head_reply, require_active_operation


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
        parent = None
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


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["cancelled", "failed", "succeeded", "queued"])
async def test_revoked_operation_cannot_continue(state):
    with pytest.raises(asyncio.CancelledError):
        require_active_operation(state)


@pytest.mark.asyncio
async def test_swallowed_cancellation_cannot_continue_running_operation():
    entered = asyncio.Event()

    async def worker():
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass
        require_active_operation("running")
        return {"ok": True}

    task = asyncio.create_task(worker())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_active_operation_may_continue():
    require_active_operation("running")


@pytest.mark.asyncio
@pytest.mark.parametrize("translated_error", [False, True])
async def test_cancelled_child_cannot_publish_a_late_reply(translated_error):
    entered = asyncio.Event()

    async def adapter():
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            if translated_error:
                raise RuntimeError("adapter translated cancellation") from None
            return {"ok": True}

    child = asyncio.create_task(adapter())
    waiter = asyncio.create_task(
        _bounded_head_reply(child, seconds=1, timeout_message="timeout")
    )
    try:
        await asyncio.wait_for(entered.wait(), 1)
        child.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
    finally:
        await asyncio.gather(child, waiter, return_exceptions=True)


@pytest.mark.asyncio
async def test_bounded_reply_accepts_uncancelled_future():
    future = asyncio.get_running_loop().create_future()
    future.set_result({"ok": True})
    assert await _bounded_head_reply(future, seconds=1, timeout_message="timeout") == {
        "ok": True
    }


@pytest.mark.asyncio
async def test_cancelled_parent_can_await_fresh_cleanup_reply():
    entered = asyncio.Event()

    async def cleanup():
        return {"ok": True}

    async def worker():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            assert await _bounded_head_reply(cleanup(), seconds=1, timeout_message="timeout") == {
                "ok": True
            }

    task = asyncio.create_task(worker())
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
