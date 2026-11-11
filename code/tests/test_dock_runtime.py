"""Dock observation must never gain motor/charging rights from JPEG geometry."""
import json
from types import SimpleNamespace

import pytest

from desk_robot import dock_runtime
from desk_robot.dock_vision import DockPose


class Head:
    def __init__(self):
        self.captures = 0
        self.commands = []

    async def snapshot(self):
        self.captures += 1
        return b"\xff\xd8\xff\xd9"

    async def command(self, command):
        self.commands.append(command)


async def test_absent_calibration_holds_without_camera_or_motors():
    head = Head()
    result = await dock_runtime.observe_actual_dock(
        head, SimpleNamespace(id="robot-01", dock_calibration=None)
    )
    assert result["phase"] == "hold"
    assert not result["motor_authorized"] and not result["charging_authorized"]
    assert not head.captures and not head.commands


async def test_measured_marker_pose_does_not_energize_contact_or_drive(tmp_path, monkeypatch):
    path = tmp_path / "dock.json"
    path.write_text(json.dumps({
        "measured": True, "fx": 410, "fy": 408, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 12, "target_distance_mm": 120,
    }))
    head = Head()

    def detector(image, calibration, *, captured_at):
        assert image.startswith(b"\xff\xd8") and calibration.marker_id == 12
        return DockPose(0, 0, 450, 0.5, captured_at)

    monkeypatch.setattr(dock_runtime, "detect_apriltag", detector)
    result = await dock_runtime.observe_actual_dock(
        head, SimpleNamespace(id="robot-01", dock_calibration=path)
    )
    assert result["phase"] == "approach"
    assert result["pose"]["z_mm"] == 450
    assert result["motor_authorized"] is False
    assert result["charging_authorized"] is False
    assert result["physical_acceptance_pass"] is False
    assert head.captures == 1 and not head.commands


@pytest.mark.parametrize("change", [
    {"measured": False}, {"fx": 0}, {"tag_side_mm": 500},
    {"target_distance_mm": 0},
])
async def test_fake_or_bad_dock_calibration_never_looks_or_drives(tmp_path, change):
    data = {
        "measured": True, "fx": 410, "fy": 410, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 12, "target_distance_mm": 120,
    }
    data.update(change)
    path = tmp_path / "dock.json"
    path.write_text(json.dumps(data))
    head = Head()
    result = await dock_runtime.observe_actual_dock(
        head, SimpleNamespace(id="robot-01", dock_calibration=path)
    )
    assert result["phase"] == "hold"
    assert head.captures == 0 and not head.commands
