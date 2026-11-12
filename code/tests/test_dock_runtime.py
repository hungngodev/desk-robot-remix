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
    assert result["source"] == "not_calibrated"
    assert result["pose"] is None
    assert result["physical_acceptance_pass"] is False
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



async def test_slow_apriltag_diagnostic_holds_stale_pose_without_any_motion(
    tmp_path, monkeypatch,
):
    import time
    calibration = tmp_path / "dock.json"
    calibration.write_text(json.dumps({
        "measured": True, "fx": 410, "fy": 410, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 12, "target_distance_mm": 120,
    }))
    head = Head()

    def slow_detector(image, camera, *, captured_at):
        time.sleep(0.25)
        return DockPose(0, 0, 450, 0.5, captured_at)

    monkeypatch.setattr(dock_runtime, "detect_apriltag", slow_detector)
    result = await dock_runtime.observe_actual_dock(
        head, SimpleNamespace(id="robot-01", dock_calibration=calibration)
    )
    assert result["phase"] == "hold"
    assert "stale" in result["reason"].lower()
    assert result["motor_authorized"] is False
    assert result["charging_authorized"] is False
    assert head.captures == 1 and head.commands == []


@pytest.mark.parametrize("failure", [OSError("camera disconnected"), TimeoutError()])
async def test_snapshot_failure_holds_without_motion(tmp_path, monkeypatch, failure):
    path = tmp_path / "dock.json"
    path.write_text(json.dumps({
        "measured": True, "fx": 410, "fy": 410, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 12, "target_distance_mm": 120,
    }))
    head = Head()

    async def failed_snapshot():
        raise failure

    monkeypatch.setattr(head, "snapshot", failed_snapshot)
    result = await dock_runtime.observe_actual_dock(
        head, SimpleNamespace(id="robot-01", dock_calibration=path)
    )
    assert result["phase"] == "hold"
    assert result["source"] == "head_snapshot_failed"
    assert result["pose"] is None
    assert result["motor_authorized"] is False
    assert result["charging_authorized"] is False
    assert result["physical_acceptance_pass"] is False
    assert head.commands == []


@pytest.mark.parametrize("failure", [RuntimeError("decoder failed"), TimeoutError()])
async def test_detector_failure_holds_without_motion(tmp_path, monkeypatch, failure):
    path = tmp_path / "dock.json"
    path.write_text(json.dumps({
        "measured": True, "fx": 410, "fy": 410, "cx": 320, "cy": 240,
        "tag_side_mm": 60, "marker_id": 12, "target_distance_mm": 120,
    }))
    head = Head()

    def failed_detector(*args, **kwargs):
        raise failure

    monkeypatch.setattr(dock_runtime, "detect_apriltag", failed_detector)
    result = await dock_runtime.observe_actual_dock(
        head, SimpleNamespace(id="robot-01", dock_calibration=path)
    )
    assert result["phase"] == "hold"
    assert result["source"] == "apriltag_detection_failed"
    assert result["pose"] is None
    assert result["motor_authorized"] is False
    assert result["charging_authorized"] is False
    assert result["physical_acceptance_pass"] is False
    assert head.commands == []
