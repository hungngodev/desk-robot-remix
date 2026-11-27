"""A retired docking operation cannot consume late camera or IR evidence."""
from __future__ import annotations

import asyncio
import time

import pytest
from desk_robot import controller
from desk_robot.controller import Coordinator, Job
from desk_robot.dock_ir import dock_beacon_code
from desk_robot.dock_vision import DockCameraCalibration, DockPose
from desk_robot.simulator import SimulationVision

STAGES = ("health", "snapshot", "identity", "detector", "ir", "health_after_ir", "verify")


@pytest.mark.parametrize("stage", STAGES)
async def test_retired_dock_stops_at_next_await(settings, monkeypatch, stage):
    settings.mode = "hardware"
    settings.robots[0].dock_beacon_id = 1
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def checkpoint(name):
        calls.append(name)
        if name == stage:
            entered.set()
            await release.wait()

    class Head:
        async def snapshot_for_dock(self):
            await checkpoint("snapshot")
            return b"jpeg", time.monotonic(), (1, 1, 1), 1

        snapshot = snapshot_for_dock

        async def camera_identity(self, receipt):
            await checkpoint("identity")
            return "OV5640"

        async def ir_status(self):
            await checkpoint("ir")
            return {
                "robot_id": "robot-01",
                "left_valid": True, "right_valid": True, "match": True,
                "left_seq": 8, "right_seq": 9,
                "left_age_ms": 0, "right_age_ms": 0,
                "code": dock_beacon_code(1),
                "left_code": dock_beacon_code(1),
                "right_code": dock_beacon_code(1),
                "motor_authorized": False, "charging_authorized": False,
                "physical_qualified": False,
            }

        async def dock_receipt_current(self, receipt):
            await checkpoint("verify")

        async def command(self, command):
            pytest.fail(f"Retired attempt sent {command}")

    async def health(*args, **kwargs):
        await checkpoint("health_after_ir" if "ir" in calls else "health")
        return {"ranges": {"mm": [50, 50, 50, 50, 600]}}

    async def detect(jpeg, camera, *, captured_at):
        await checkpoint("detector")
        return DockPose(0, 0, 500, 0.5, captured_at)

    coordinator = Coordinator(settings, {"robot-01": Head()}, SimulationVision())
    monkeypatch.setattr(coordinator, "_assert_armed_health", health)
    monkeypatch.setattr(controller, "detect_bounded", detect)
    robot_id = "robot-01"
    job = Job("first-attempt", robot_id, "dock_approach",
              _motion_epoch=coordinator._permit_epoch[robot_id])
    coordinator._fleet_motion_owner = job.id
    camera = DockCameraCalibration(
        410, 410, 320, 240, 60, 1, camera_sensor_pid="OV5640",
        mount_lateral_offset_mm=0, mount_yaw_deg=0, mount_forward_offset_mm=0,
    )
    task = asyncio.create_task(coordinator._dock_approach(job, camera, 200, 1, 1))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        # Model the common ownership revocation used by STOP and job teardown.
        # Deliberately let the old adapter reply instead of cancelling its task.
        coordinator._retire_permit(robot_id)
        coordinator._fleet_motion_owner = "second-attempt"
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert calls == list(STAGES[:STAGES.index(stage) + 1])
        assert coordinator._fleet_motion_owner == "second-attempt"
        assert job.result is None
        if stage in ("health", "snapshot", "identity", "detector"):
            assert not job.events
    finally:
        release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
