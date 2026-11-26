import asyncio

import pytest
from desk_robot.vision_admission import VisionCallAdmission, vision_lock_until


async def test_queued_vision_expires_without_releasing_another_owner():
    lock = asyncio.Lock()
    await lock.acquire()
    try:
        with pytest.raises(RuntimeError, match="expired while queued"):
            async with vision_lock_until(lock, 0.01):
                pytest.fail("Expired queue entry acquired the lock")
        assert lock.locked()
    finally:
        lock.release()
    async with vision_lock_until(lock, 1):
        assert lock.locked()
    assert not lock.locked()


async def test_vision_lock_releases_on_owner_cancellation():
    lock = asyncio.Lock()
    entered = asyncio.Event()

    async def owner():
        async with vision_lock_until(lock, 1):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(owner())
    try:
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not lock.locked()
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_vision_calls_bound_cancellation_resistant_tasks_and_recover():
    admission = VisionCallAdmission()
    entered = asyncio.Queue()
    release = asyncio.Event()
    cancelled = asyncio.Queue()

    async def stubborn():
        entered.put_nowait(True)
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.put_nowait(True)
            await release.wait()
            raise ValueError("late failure")

    def forbidden():
        pytest.fail("Saturated admission constructed another model coroutine")

    tasks = []
    try:
        for _ in range(2):
            task = admission.start(stubborn)
            tasks.append(task)
            await asyncio.wait_for(entered.get(), 1)
            task.cancel()
            await asyncio.wait_for(cancelled.get(), 1)
        assert admission.active() == set(tasks)
        for _ in range(10):
            with pytest.raises(RuntimeError, match="capacity occupied"):
                admission.start(forbidden)
        release.set()
        await asyncio.wait(tasks, timeout=1)
        await asyncio.sleep(0)
        assert not admission.active()
        assert not admission._tasks

        async def fresh():
            return "fresh"

        assert await admission.start(fresh) == "fresh"
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
