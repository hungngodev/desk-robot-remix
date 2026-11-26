import asyncio
from collections import deque
from types import SimpleNamespace

import pytest
from desk_robot.controller import Coordinator, DeferredMotionRequest


@pytest.mark.asyncio
@pytest.mark.parametrize("swallow", [False, True])
async def test_cancelled_deferred_preflight_discards_request(swallow):
    started = asyncio.Event()

    async def preflight(robot_id):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            if not swallow:
                raise

    def submit():
        pytest.fail("Cancelled deferred motion must never submit a job")

    request = DeferredMotionRequest("request", "pet", "manual", float("inf"), 0, submit)
    coordinator = SimpleNamespace(
        _ensure_voice_gate=lambda: None,
        _deferred_dispatch_lock=asyncio.Lock(),
        _deferred_voice_queue=deque([request]),
        _deferred_voice_generation=0,
        _fleet_motion_owner=None,
        _permit_epoch={"pet": 0},
        _stop_confirmations=SimpleNamespace(blocked=lambda robot_id: False),
        voice_blocks_motion=lambda: None,
        robot=lambda robot_id: SimpleNamespace(motion_enabled=True),
        dock_inhibited=lambda robot_id: False,
        _hardware_preflight=preflight,
        permits={},
        closed=False,
    )
    task = asyncio.create_task(Coordinator.dispatch_next_deferred(coordinator))
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
        assert request.state == "discarded"
        assert "cancelled" in request.error
        assert not coordinator.permits
        assert not coordinator._deferred_voice_queue
        assert request.job_id is None
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
