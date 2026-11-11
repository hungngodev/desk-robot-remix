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
