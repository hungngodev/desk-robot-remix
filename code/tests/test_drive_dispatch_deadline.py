"""A queued Mac drive cannot restart motion after its dispatch window expires."""

import asyncio
import time

import pytest
from desk_robot import operations
from desk_robot.command_framing import expected_ack
from desk_robot.operations import OperationError, dispatch_job_command


class QueuedHead:
    supports_dispatch_check = True

    def __init__(self):
        self.queued = asyncio.Event()
        self.release = asyncio.Event()
        self.sent = []

    async def command(self, command, *, dispatch_check):
        self.queued.set()
        await self.release.wait()
        dispatch_check()
        self.sent.append(command)
        return {"ok": True, "robot_id": "robot-01", "reply": expected_ack(command)}


@pytest.mark.asyncio
async def test_400ms_event_loop_stall_prevents_queued_drive():
    head = QueuedHead()
    task = asyncio.create_task(
        dispatch_job_command(head, "drive 20 20 250", lambda: None, robot_id="robot-01")
    )
    await head.queued.wait()
    time.sleep(0.4)  # deliberately starve the event loop, not merely this coroutine
    head.release.set()
    with pytest.raises(OperationError, match="Drive dispatch expired"):
        await task
    assert head.sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("command", "age", "expired"),
    [("drive 20 20", 0.249, False), ("drive 20 20", 0.250, True), ("halt", 0.4, False)],
)
async def test_dispatch_deadline_boundary(monkeypatch, command, age, expired):
    clock = [0.0]
    monkeypatch.setattr(operations, "monotonic", lambda: clock[0], raising=False)
    head = QueuedHead()
    task = asyncio.create_task(
        dispatch_job_command(head, command, lambda: None, robot_id="robot-01")
    )
    await head.queued.wait()
    clock[0] = age
    head.release.set()
    if expired:
        with pytest.raises(OperationError, match="Drive dispatch expired"):
            await task
        assert head.sent == []
    else:
        assert await task == {
            "ok": True, "robot_id": "robot-01", "reply": expected_ack(command),
        }
        assert head.sent == [command]


@pytest.mark.asyncio
@pytest.mark.parametrize("retire_at", ["before_send", "before_ack"])
async def test_retired_motion_epoch_rejects_old_drive_or_receipt(monkeypatch, retire_at):
    """A stale route segment must not survive an authority change at either boundary."""
    monkeypatch.setattr(operations, "monotonic", lambda: 0.0)
    epoch = 1
    admitted_epoch = epoch
    sent = []
    suspended = asyncio.Event()
    release = asyncio.Event()

    def check_authority():
        if epoch != admitted_epoch:
            raise asyncio.CancelledError

    class Head:
        supports_dispatch_check = True

        async def command(self, command, *, dispatch_check):
            if retire_at == "before_send":
                suspended.set()
                await release.wait()
            dispatch_check()
            sent.append(command)
            if retire_at == "before_ack":
                suspended.set()
                await release.wait()
            return {"ok": True, "robot_id": "robot-01", "reply": expected_ack(command)}

    old_command = "drive 20 20 100"
    task = asyncio.create_task(
        dispatch_job_command(Head(), old_command, check_authority, robot_id="robot-01")
    )
    await asyncio.wait_for(suspended.wait(), timeout=1)
    epoch += 1
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=1)
    assert sent == ([old_command] if retire_at == "before_ack" else [])
