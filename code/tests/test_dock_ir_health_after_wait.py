"""Dock pulse authority must not reuse body health from before a slow IR read."""
from __future__ import annotations

import asyncio
import time

import pytest
from desk_robot.controller import Coordinator, Job, OperationError
from desk_robot.dock_ir import dock_beacon_code
from desk_robot.dock_vision import DockCameraCalibration, DockPose
from desk_robot.simulator import SimulationVision


@pytest.mark.parametrize("changed,pose_x", [
    ("disarmed", 80), ("side_blocked", 80), ("front_blocked", 0),
    ("healthy", 0),
    ("slow_ir_left", 0), ("slow_ir_right", 0),
    ("slow_body", 0), ("stream_restarted", 0),
])
async def test_dock_rechecks_real_body_safety_after_waiting_for_ir(
    settings, monkeypatch, changed, pose_x,
):
    settings.mode = "hardware"
    settings.robots[0].dock_beacon_id = 1
    started = asyncio.Event()
    release = asyncio.Event()

    class Head:
        def __init__(self):
            self.commands = []
            self.reads = 0
            self.changed = None

        async def status(self):
            self.reads += 1
            if self.changed == "slow_body" and self.reads >= 2:
                await asyncio.sleep(0.16)
            disarmed = self.changed == "disarmed"
            side = [600, 600, 600]
            if self.changed == "side_blocked":
                side[0] = 200
            front = 320 if self.changed == "front_blocked" else 600
            return {
                "robot_id": "robot-01", "armed": not disarmed,
                "safety": {"required": True, "ready": not disarmed,
                           "fault": "missing_sample" if disarmed else "none"},
                "ranges": {"present_mask": 31, "valid_mask": 31,
                           "mm": [50, 50, 50, 50, front],
                           "age_ms": [5, 5, 5, 5, 5]},
                "imu": {"valid": True, "age_ms": 10},
                "touch": {"active": False},
                "side_ranges": {"present_mask": 7, "valid_mask": 7,
                                "age_ms": [10, 10, 10], "mm": side},
            }

        async def snapshot_for_dock(self):
            return (b"valid-identity-placeholder",
                    time.monotonic(), (1234, 1, 1), 1)

        async def dock_receipt_current(self, receipt):
            if self.changed == "stream_restarted":
                raise ValueError("Camera stream boot changed after IR wait")
            assert receipt[2:] == ((1234, 1, 1), 1)

        async def snapshot(self):
            raise AssertionError("Dock must use its fresh camera entry")

        async def ir_status(self):
            started.set()
            await release.wait()
            if self.changed in ("slow_ir_left", "slow_ir_right"):
                await asyncio.sleep(0.16)
            return {
                "robot_id": "robot-01",
                "left_valid": True, "right_valid": True, "match": True,
                "left_seq": 8, "right_seq": 9,
                "left_age_ms": 85 if self.changed in ("slow_ir_left", "slow_body") else 0,
                "right_age_ms": 85 if self.changed == "slow_ir_right" else 0,
                "code": dock_beacon_code(1),
                "motor_authorized": False, "charging_authorized": False,
                "physical_qualified": False,
            }

        async def command(self, command):
            self.commands.append(command)
            return {"ok": True, "robot_id": "robot-01", "reply": "OK " + command}

    head = Head()
    coordinator = Coordinator(settings, {"robot-01": head}, SimulationVision())
    camera = DockCameraCalibration(
        410, 410, 320, 240, 60, 1,
        mount_lateral_offset_mm=0, mount_yaw_deg=0,
    )
    observations = iter((500, 150))
    monkeypatch.setattr(
        "desk_robot.dock_runtime.detect_apriltag",
        lambda jpeg, cal, *, captured_at:
            DockPose(pose_x, 0, next(observations), 0.5, captured_at),
    )
    task = asyncio.create_task(coordinator._dock_approach(
        Job("dock-ir-race", "robot-01", "dock_approach"),
        camera, 200, 1, 1,
    ))
    try:
        await asyncio.wait_for(started.wait(), 1.5)
        head.changed = None if changed == "healthy" else changed
        release.set()
        if changed in (
            "disarmed", "side_blocked", "slow_ir_left", "slow_ir_right",
            "stream_restarted",
        ):
            with pytest.raises(OperationError):
                await asyncio.wait_for(task, 2)
            assert head.commands == []
        else:
            result = await asyncio.wait_for(task, 2)
            assert result["phase"] == "hold"
            assert result["charging_authorized"] is False
            if changed in ("front_blocked", "slow_body"):
                assert head.commands == []
            else:
                assert head.commands == ["drive 20 20 100", "stop"]
        # Slow IR is rejected before a second body-health round trip.
        assert head.reads >= (1 if changed.startswith("slow_ir") else 2)
    finally:
        release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await coordinator.close()
