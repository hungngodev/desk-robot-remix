import asyncio

import pytest
from desk_robot.vision_admission import FrameAdmissionDropped, LatestFrameAdmission


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [True, False, None, "1", float("nan"), float("inf"),
                                  -float("inf"), 10**400], ids=lambda value: type(value).__name__)
@pytest.mark.parametrize("field", ["receipt", "clock"])
async def test_invalid_frame_time_never_reserves_or_mutates_queue(bad, field):
    gate = LatestFrameAdmission()
    reserved = []
    received = bad if field == "receipt" else 1.0
    now = bad if field == "clock" else 1.0

    def reserve():
        reserved.append(True)
        return True

    with pytest.raises(FrameAdmissionDropped, match="invalidated or expired"):
        await gate.acquire("robot-01", received, clock=lambda: now,
                           reserve=reserve, admit=lambda: True)
    assert not reserved
    assert not gate._pending


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [True, None, float("nan"), 10**400])
async def test_invalid_clock_after_enqueue_retires_ticket(bad):
    gate = LatestFrameAdmission()
    now = 1.0
    reserved = []
    available = False

    def reserve():
        if not available:
            return False
        reserved.append(True)
        return True

    async def offer():
        await gate.acquire("robot-01", 1.0, clock=lambda: now,
                           reserve=reserve, admit=lambda: True)

    pending = asyncio.create_task(offer())
    await asyncio.sleep(0)
    assert len(gate._pending) == 1
    now = bad
    available = True
    gate.notify()
    with pytest.raises(FrameAdmissionDropped, match="invalidated or expired"):
        await pending
    assert not reserved
    assert not gate._pending
    now = 1.0
    await offer()
    assert reserved == [True]
