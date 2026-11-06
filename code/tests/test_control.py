import asyncio
import time

import pytest
from desk_robot.controller import Coordinator, OperationError
from desk_robot.simulator import SimulatedHead, SimulationVision


def make(settings):
    head = SimulatedHead("robot-01")
    heads = {"robot-01": head, "robot-02": SimulatedHead("robot-02")}
    return Coordinator(settings, heads, SimulationVision()), head


async def test_permit_is_operator_only_one_use_per_robot(settings):
    c, head = make(settings)
    try:
        with pytest.raises(OperationError, match="permit"):
            c.manual("robot-01", "drive 20 20 100")
        permit = await c.operator_arm("robot-01")
        assert not permit["physical_armed"] and head.commands == []
        with pytest.raises(OperationError, match="permit"):
            c.manual("robot-02", "drive 20 20 100")
        job = c.manual("robot-01", "drive 20 20 100")
        await c.tasks[job.id]
        assert job.state == "succeeded"
        assert head.commands[0] == "arm" and head.commands[-1] == "stop"
        assert head.commands.count("drive 20 20 100") == 1
        with pytest.raises(OperationError, match="permit"):
            c.manual("robot-01", "drive 20 20 100")
    finally:
        await c.close()


async def test_permit_expiry_motion_default_and_simulation_calibration(settings):
    c, head = make(settings)
    settings.robots[0].motion_enabled = False
    with pytest.raises(OperationError, match="motion_enabled"):
        await c.operator_arm("robot-01")
    settings.robots[0].motion_enabled = True
    c.permits["robot-01"] = time.monotonic() - 1
    with pytest.raises(OperationError, match="expired"):
        c.manual("robot-01", "lift 90")
    settings.mode = "hardware"
    with pytest.raises(OperationError, match="Simulation calibration"):
        c.pickup("robot-01", "key")
    assert head.commands == []


@pytest.mark.parametrize("failure", ["drive", "keepalive"])
async def test_uncertain_commands_not_retried_and_stop_finally(settings, failure):
    c, head = make(settings)
    head.fail_command = failure
    try:
        await c.operator_arm("robot-01")
        job = c.manual("robot-01", "drive 20 20 100")
        await c.tasks[job.id]
        assert job.state == "failed"
        assert head.commands[-1] == "stop"
        assert head.commands.count("drive 20 20 100") <= 1
    finally:
        await c.close()


async def test_cancel_queued_job_can_enable_next_job(settings):
    c, head = make(settings)
    try:
        await c.operator_arm("robot-01")
        job = c.manual("robot-01", "lift 110")
        await c.stop("robot-01")
        assert job.state == "cancelled"
        await c.operator_arm("robot-01")
        next_job = c.manual("robot-01", "drive 0 0 1")
        await c.tasks[next_job.id]
        assert next_job.state == "succeeded"
    finally:
        await c.close()


async def test_deadline_cancels_work_and_stop(settings):
    settings.max_job_seconds = 1
    c, head = make(settings)
    try:
        await c.operator_arm("robot-01")
        job = c.manual("robot-01", "lift 110")
        await c.tasks[job.id]
        assert job.state == "failed" and head.commands[-1] == "stop"
    finally:
        await c.close()


async def test_simulated_closed_loop_pickup_is_not_acceptance(settings):
    c, head = make(settings)
    try:
        await c.operator_arm("robot-01")
        job = c.pickup("robot-01", "key")
        await c.tasks[job.id]
        assert job.state == "succeeded", job.error
        assert job.result["visually_verified"]
        assert job.result["physical_acceptance_pass"] is False
        assert any(s.startswith("drive ") for s in head.commands)
        assert head.commands[-1] == "stop"
    finally:
        await c.close()


@pytest.mark.parametrize("fault", ["lost", "camera", "not_lifted"])
async def test_pickup_failures_stop(settings, fault):
    c, head = make(settings)
    if fault == "lost":
        head.show_target = False
    elif fault == "camera":
        head.fail_snapshot = True
    else:
        original = head.command

        async def no_lift(command):
            result = await original(command)
            head.lifted = False
            return result

        head.command = no_lift
    try:
        await c.operator_arm("robot-01")
        job = c.pickup("robot-01", "candy")
        await c.tasks[job.id]
        assert job.state == "failed" and head.commands[-1] == "stop"
        assert job.result is None
    finally:
        await c.close()


async def test_cancel_running_job_stops_and_ends_keepalive(settings):
    c, head = make(settings)
    try:
        await c.operator_arm("robot-01")
        job = c.manual("robot-01", "lift 110")
        await asyncio.sleep(0.05)
        await c.stop("robot-01")
        assert job.state == "cancelled"
        count = len(head.commands)
        await asyncio.sleep(0.15)
        assert len(head.commands) == count
    finally:
        await c.close()
