"""Dock pulses must retain fleet ownership through the transport queue."""
import asyncio

import pytest
from desk_robot import operations
from desk_robot.command_framing import MAX_DRIVE_DURATION_MS, expected_ack
from desk_robot.controller import Coordinator, Job, OperationError


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["valid", "peer_owner", "retired_epoch", "deadline"])
async def test_dock_pulse_rechecks_fleet_authority_at_dispatch(monkeypatch, boundary):
    entered, release = asyncio.Event(), asyncio.Event()
    sent = []
    now = 10.0
    monkeypatch.setattr(operations, "monotonic", lambda: now)

    class QueuedHead:
        supports_dispatch_check = True

        async def command(self, command, *, dispatch_check):
            entered.set()
            await release.wait()
            dispatch_check()
            sent.append(command)
            return {
                "ok": True, "robot_id": "robot-01", "reply": expected_ack(command),
            }

    coordinator = object.__new__(Coordinator)
    job = Job("dock", "robot-01", "dock_approach", state="running", _motion_epoch=1)
    coordinator.closed = False
    coordinator.tasks = {}
    coordinator.jobs = {job.id: job}
    coordinator._permit_epoch = {job.robot_id: 1}
    coordinator._fleet_motion_owner = job.id
    coordinator.heads = {job.robot_id: QueuedHead()}
    command = "drive 20 20 100"
    task = asyncio.create_task(coordinator._motion_command(job, command))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        if boundary == "peer_owner":
            coordinator._fleet_motion_owner = "peer-job"
        elif boundary == "retired_epoch":
            coordinator._permit_epoch[job.robot_id] += 1
        elif boundary == "deadline":
            assert MAX_DRIVE_DURATION_MS == 250
            now += 0.250
        release.set()
        if boundary == "valid":
            assert await task == {
                "ok": True, "robot_id": job.robot_id, "reply": expected_ack(command),
            }
            assert sent == [command]
        elif boundary == "deadline":
            with pytest.raises(OperationError, match="Drive dispatch expired"):
                await task
            assert not sent
        else:
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not sent
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
