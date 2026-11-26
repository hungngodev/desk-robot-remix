import asyncio
import time

import pytest
from desk_robot.vision_admission import LatestFrameAdmission


@pytest.mark.asyncio
async def test_flood_replaces_only_own_ticket_without_jumping_fleet_order():
    gate = LatestFrameAdmission()
    busy = True
    admitted = []

    def reserve():
        nonlocal busy
        if busy:
            return False
        busy = True
        return True

    async def offer(robot, received):
        nonlocal busy
        await gate.acquire(robot, received, clock=time.monotonic,
                           reserve=reserve, admit=lambda: True)
        admitted.append((robot, received))
        busy = False
        gate.notify()

    stamp = time.monotonic()
    pets = [f"robot-{index:02d}" for index in range(1, 6)]
    first = [asyncio.create_task(offer(robot, stamp)) for robot in pets]
    await asyncio.sleep(0)
    flood = []
    for _ in range(20):
        flood.append(asyncio.create_task(offer(pets[0], time.monotonic())))
        await asyncio.sleep(0)
    latest = flood[-1]
    assert len(gate._pending) == 5
    busy = False
    gate.notify()
    results = await asyncio.wait_for(
        asyncio.gather(*first, *flood, return_exceptions=True), 2,
    )
    assert all(isinstance(result, RuntimeError) for result in [results[0], *results[5:-1]])
    assert latest.result() is None
    assert [robot for robot, _ in admitted] == pets
    assert admitted[0][1] > stamp
    assert not gate._pending


@pytest.mark.asyncio
async def test_cancel_revocation_and_close_do_not_reserve_or_block_peers():
    gate = LatestFrameAdmission()
    admitted = []
    allowed = True
    busy = True

    def reserve():
        if busy:
            return False
        admitted.append(True)
        return True

    async def offer(robot):
        await gate.acquire(robot, time.monotonic(), clock=time.monotonic,
                           reserve=reserve, admit=lambda: allowed)

    cancelled = asyncio.create_task(offer("robot-01"))
    revoked = asyncio.create_task(offer("robot-02"))
    await asyncio.sleep(0)
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    allowed = False
    gate.notify()
    with pytest.raises(RuntimeError, match="invalidated"):
        await revoked
    assert not gate._pending
    allowed = True
    busy = False
    await offer("robot-03")
    assert admitted == [True]
    busy = True
    pending = asyncio.create_task(offer("robot-04"))
    await asyncio.sleep(0)
    gate.close()
    with pytest.raises(RuntimeError, match="invalidated"):
        await pending
    assert not gate._pending
    assert admitted == [True]
