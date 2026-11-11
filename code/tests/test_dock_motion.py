"""Dock motion remains operator permitted and disabled by default."""
import json

import pytest
from desk_robot.controller import Coordinator, OperationError
from desk_robot.simulator import SimulatedHead, SimulationVision


def make(settings):
    head = SimulatedHead("robot-01")
    return Coordinator(
        settings, {"robot-01": head, "robot-02": SimulatedHead("robot-02")},
        SimulationVision(),
    ), head


def test_dock_approach_refuses_unmeasured_hardware_and_default_config(settings):
    controller, head = make(settings)
    try:
        with pytest.raises(OperationError, match="qualification"):
            controller.dock("robot-01")
        assert head.commands == []
    finally:
        # Close is async and no tasks have been started here.
        pass


async def test_dock_does_not_consume_permit_without_measured_steering(settings, tmp_path):
    settings.mode = "hardware"
    robot = settings.robots[0]
    robot.dock_motion_qualified = True
    robot.dock_turn_sign = None
    robot.dock_forward_sign = 1
    dock = tmp_path / "dock.json"
    dock.write_text(json.dumps({
        "measured": True, "fx": 410, "fy": 410, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 1, "target_distance_mm": 200,
    }))
    robot.dock_calibration = dock
    controller, head = make(settings)
    try:
        controller.permits["robot-01"] = 10**9
        with pytest.raises(OperationError, match="polarity"):
            controller.dock("robot-01")
        assert controller.permits["robot-01"] == 10**9
        assert head.commands == []
    finally:
        await controller.close()


async def test_dock_approach_rejects_turn_without_three_fresh_clear_ranges(
    settings, monkeypatch,
):
    from desk_robot.controller import Job
    from desk_robot.dock_vision import DockCameraCalibration, DockPose

    settings.mode = "hardware"

    class SensorHead:
        def __init__(self):
            self.commands = []

        async def status(self):
            return {
                "armed": True,
                "safety": {"required": True, "ready": True, "fault": "none"},
                "ranges": {"present_mask": 31, "valid_mask": 31,
                           "mm": [50, 50, 50, 50, 650],
                           "age_ms": [5, 5, 5, 5, 5]},
                "imu": {"valid": True, "age_ms": 10},
                "touch": {"active": False},
                "side_ranges": {"valid_mask": 0, "age_ms": [10, 10, 10],
                                "mm": [600, 600, 600]},
            }

        async def snapshot(self):
            return b"simulated marker image"

        async def command(self, text):
            self.commands.append(text)

    head = SensorHead()
    controller = Coordinator(
        settings, {"robot-01": head}, SimulationVision(),
    )
    camera = DockCameraCalibration(
        fx=410, fy=410, cx=320, cy=240,
        tag_side_mm=60, marker_id=1,
    )
    monkeypatch.setattr(
        "desk_robot.controller.detect_apriltag",
        lambda jpeg, cal, *, captured_at: DockPose(
            80, 0, 500, 0.5, captured_at,
        ),
    )
    try:
        with pytest.raises(OperationError, match="side and rear"):
            await controller._dock_approach(
                Job("dock-unit", "robot-01", "dock_approach"),
                camera, 200, 1, 1,
            )
        assert head.commands == []
    finally:
        await controller.close()


async def test_dock_approach_moves_once_then_holds_before_contacts(
    settings, monkeypatch,
):
    from desk_robot.controller import Job
    from desk_robot.dock_vision import DockCameraCalibration, DockPose

    settings.mode = "hardware"

    class GuardedHead:
        def __init__(self):
            self.commands = []

        async def status(self):
            return {
                "armed": True,
                "safety": {"required": True, "ready": True, "fault": "none"},
                "ranges": {"present_mask": 31, "valid_mask": 31,
                           "mm": [50, 50, 50, 50, 600],
                           "age_ms": [5, 5, 5, 5, 5]},
                "imu": {"valid": True, "age_ms": 10},
                "touch": {"active": False},
                "side_ranges": {"valid_mask": 7, "age_ms": [10, 10, 10],
                                "mm": [600, 600, 600]},
            }

        async def snapshot(self):
            return b"simulated marker image"

        async def command(self, text):
            self.commands.append(text)

    head = GuardedHead()
    controller = Coordinator(settings, {"robot-01": head}, SimulationVision())
    camera = DockCameraCalibration(
        fx=410, fy=410, cx=320, cy=240, tag_side_mm=60, marker_id=1,
    )
    distances = iter((500, 150))
    monkeypatch.setattr(
        "desk_robot.controller.detect_apriltag",
        lambda jpeg, cal, *, captured_at: DockPose(
            0, 0, next(distances), 0.5, captured_at,
        ),
    )
    try:
        result = await controller._dock_approach(
            Job("dock-unit", "robot-01", "dock_approach"),
            camera, 200, 1, 1,
        )
        assert result["phase"] == "hold"
        assert not result["charging_authorized"]
        assert not result["physical_acceptance_pass"]
        assert head.commands == ["drive 20 20 100", "stop"]
    finally:
        await controller.close()


async def test_dock_approach_requires_operator_permit_after_qualification(settings, tmp_path):
    settings.mode = "hardware"
    robot = settings.robots[0]
    robot.dock_motion_qualified = True
    robot.dock_turn_sign = 1
    robot.dock_forward_sign = 1
    path = tmp_path / "dock.json"
    path.write_text(json.dumps({
        "measured": True, "fx": 410, "fy": 410, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 1, "target_distance_mm": 200,
    }))
    robot.dock_calibration = path
    controller, head = make(settings)
    try:
        with pytest.raises(OperationError, match="permit"):
            controller.dock("robot-01")
        assert head.commands == []
    finally:
        await controller.close()
