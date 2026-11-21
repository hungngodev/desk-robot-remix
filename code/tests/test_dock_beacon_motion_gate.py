"""Actual camera approach must check the assigned physical dual NEC station.

These are simulated host contract tests. They do not certify beacon optics,
local WROOM sensor geometry, battery charging, or loaded motor stopping.
"""
import pytest
from desk_robot.controller import Coordinator, Job, OperationError
from desk_robot.dock_vision import DockCameraCalibration, DockPose
from desk_robot.simulator import SimulationVision


class SensorHead:
    def __init__(self, station=0xce31ed12, *, fresh=True, matching=True):
        self.station = station
        self.fresh = fresh
        self.matching = matching
        self.reads = 0
        self.commands = []

    async def status(self):
        return {
            "robot_id": "robot-01", "armed": True,
            "safety": {"required": True, "ready": True, "fault": "none"},
            "ranges": {"present_mask": 31, "valid_mask": 31,
                       "mm": [50, 50, 50, 50, 700], "age_ms": [5] * 5},
            "imu": {"valid": True, "age_ms": 5},
            "touch": {"active": False},
            "side_ranges": {"present_mask": 7, "valid_mask": 7,
                            "mm": [600, 600, 600], "age_ms": [5] * 3},
        }

    async def snapshot(self):
        return b"test-only-camera-image"

    async def ir_status(self):
        self.reads += 1
        seq = self.reads if self.fresh else 1
        return {
            "robot_id": "robot-01",
            "left_valid": self.matching,
            "right_valid": self.matching,
            "match": self.matching,
            "left_seq": seq,
            "right_seq": seq,
            "left_age_ms": 10,
            "right_age_ms": 10,
            "code": self.station if self.matching else 0,
            "motor_authorized": False,
            "charging_authorized": False,
            "physical_qualified": False,
        }

    async def command(self, command):
        self.commands.append(command)


def camera():
    return DockCameraCalibration(
        410, 410, 320, 240, 60, 1,
        mount_lateral_offset_mm=0, mount_yaw_deg=0,
    )


def install_scene(monkeypatch, depths):
    measured = iter(depths)
    monkeypatch.setattr(
        "desk_robot.dock_runtime.detect_apriltag",
        lambda frame, calibration, *, captured_at: DockPose(
            0, 0, next(measured), 0.5, captured_at,
        ),
    )


async def test_foreign_five_pet_dock_beacon_blocks_actual_camera_motor_pulse(
    settings, monkeypatch,
):
    settings.mode = "hardware"
    settings.robots[0].dock_beacon_id = 1
    head = SensorHead(station=0xcb34ed12)  # assigned to robot 04
    install_scene(monkeypatch, [500])
    controller = Coordinator(settings, {"robot-01": head}, SimulationVision())
    try:
        with pytest.raises(OperationError, match="Foreign NEC dock beacon"):
            await controller._dock_approach(
                Job("foreign", "robot-01", "dock_approach"), camera(), 200, 1, 1,
            )
        assert head.commands == []
        assert head.reads == 1
    finally:
        await controller.close()


async def test_assigned_dock_beacon_allows_only_guarded_standoff_pulse(
    settings, monkeypatch,
):
    settings.mode = "hardware"
    settings.robots[0].dock_beacon_id = 1
    head = SensorHead()
    install_scene(monkeypatch, [500, 150])
    controller = Coordinator(settings, {"robot-01": head}, SimulationVision())
    try:
        result = await controller._dock_approach(
            Job("assigned", "robot-01", "dock_approach"), camera(), 200, 1, 1,
        )
        assert result["phase"] == "hold"
        assert result["charging_authorized"] is False
        assert result["physical_acceptance_pass"] is False
        assert head.commands == ["drive 20 20 100", "stop"]
        assert head.reads == 1
    finally:
        await controller.close()


async def test_replayed_assigned_dock_receiver_counters_stop_second_pulse(
    settings, monkeypatch,
):
    settings.mode = "hardware"
    settings.robots[0].dock_beacon_id = 1
    head = SensorHead(fresh=False)
    install_scene(monkeypatch, [500] * 4)
    controller = Coordinator(settings, {"robot-01": head}, SimulationVision())
    try:
        result = await controller._dock_approach(
            Job("cached", "robot-01", "dock_approach"), camera(), 200, 1, 1,
        )
        assert result["phase"] == "hold"
        assert "replay" in result["reason"].lower()
        assert head.reads == 2
        assert head.commands == ["drive 20 20 100", "stop"]
    finally:
        await controller.close()


async def test_no_joint_ir_visibility_stops_without_motor_or_charge(
    settings, monkeypatch,
):
    settings.mode = "hardware"
    settings.robots[0].dock_beacon_id = 1
    head = SensorHead(matching=False)
    install_scene(monkeypatch, [500])
    controller = Coordinator(settings, {"robot-01": head}, SimulationVision())
    try:
        result = await controller._dock_approach(
            Job("no-beacon", "robot-01", "dock_approach"), camera(), 200, 1, 1,
        )
        assert result["phase"] == "hold"
        assert result["charging_authorized"] is False
        assert head.commands == []
    finally:
        await controller.close()
