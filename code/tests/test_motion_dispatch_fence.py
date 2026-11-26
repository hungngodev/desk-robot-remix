"""Host authority must survive transport scheduling boundaries."""
import asyncio

import pytest
from desk_robot.operations import dispatch_job_command


@pytest.mark.asyncio
@pytest.mark.parametrize("revoke_at", ["before", "dispatch", "ack"])
async def test_dispatch_rejects_revoked_generation(revoke_at):
    entered = asyncio.Event()
    release = asyncio.Event()
    sent = []
    generation = 1

    def check():
        if generation != 1:
            raise asyncio.CancelledError

    class Head:
        supports_dispatch_check = True

        async def command(self, command, *, dispatch_check=None):
            if revoke_at == "dispatch":
                entered.set()
                await release.wait()
            if dispatch_check is not None:
                dispatch_check()
            sent.append(command)
            if revoke_at == "ack":
                entered.set()
                await release.wait()
            return {"ok": True}

    if revoke_at == "before":
        generation += 1
    task = asyncio.create_task(dispatch_job_command(Head(), "arm", check))
    if revoke_at != "before":
        await asyncio.wait_for(entered.wait(), 1)
        generation += 1
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    assert sent == (["arm"] if revoke_at == "ack" else [])


@pytest.mark.asyncio
async def test_dispatch_preserves_legacy_adapter_success():
    class Head:
        async def command(self, command):
            return {"command": command}

    checks = []
    reply = await dispatch_job_command(Head(), "arm", lambda: checks.append(True))
    assert reply == {"command": "arm"}
    assert checks == [True, True]


@pytest.mark.asyncio
async def test_coordinator_stop_retires_delayed_manual_dispatch(settings):
    from desk_robot.controller import Coordinator
    from desk_robot.simulator import SimulatedHead, SimulationVision

    for robot in settings.robots:
        robot.motor_backend = "stepper_28byj48"
    head = SimulatedHead("robot-01")
    heads = {"robot-01": head, "robot-02": SimulatedHead("robot-02")}
    coordinator = Coordinator(settings, heads, SimulationVision())
    entered = asyncio.Event()
    release = asyncio.Event()
    halt_sent = asyncio.Event()
    attempts = []
    original = head.command
    head.supports_dispatch_check = True

    async def delayed(command, *, dispatch_check=None):
        if command.startswith("drive "):
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                # Simulate an adapter that ignores cancellation while queued.
                asyncio.current_task().uncancel()
                await release.wait()
            if dispatch_check is not None:
                dispatch_check()
            attempts.append(command)
        elif dispatch_check is not None:
            dispatch_check()
        if command == "halt":
            halt_sent.set()
        return await original(command)

    head.command = delayed
    try:
        await coordinator.operator_arm("robot-01")
        job = coordinator.manual("robot-01", "drive 20 20 100")
        await asyncio.wait_for(entered.wait(), 1)
        stopping = asyncio.create_task(coordinator.stop("robot-01"))
        await asyncio.wait_for(halt_sent.wait(), 1)
        release.set()
        await asyncio.wait_for(stopping, 3)
        assert not attempts
        assert job.state == "cancelled"
        assert job.result is None
        assert not head.armed
    finally:
        release.set()
        await coordinator.close()


@pytest.mark.asyncio
async def test_dispatch_only_evidence_is_not_rechecked_after_ack():
    valid = True
    checks = []

    def evidence():
        assert valid
        checks.append(True)

    class Head:
        supports_dispatch_check = True

        async def command(self, command, *, dispatch_check):
            nonlocal valid
            dispatch_check()
            valid = False
            return {"ok": True}

    reply = await dispatch_job_command(Head(), "drive 20 20 100", lambda: None,
                                       dispatch_check=evidence)
    assert reply == {"ok": True}
    assert checks == [True]
