"""AprilTag and NEC observation freshness must retain their exact boundaries."""

import asyncio
import math
from types import SimpleNamespace

import pytest
from desk_robot import dock_runtime
from desk_robot.dock_ir import dock_beacon_code, validate_ir
from desk_robot.dock_vision import DockPose, assess_dock


@pytest.mark.parametrize("age, expected_phase", [
    (math.nextafter(0.0, -1.0), "hold"),
    (0.0, "approach"),
    (math.nextafter(0.2, 0.0), "approach"),
    (0.2, "approach"),
    (math.nextafter(0.2, math.inf), "hold"),
])
def test_marker_age_boundary(age, expected_phase):
    pose = DockPose(0, 0, 250, 1, 0.0)
    assessment = assess_dock(pose, now=age, target_distance_mm=100)
    assert assessment.phase == expected_phase
    assert not assessment.motor_authorized
    assert not assessment.charging_authorized


def test_marker_custom_age_limit_is_preserved():
    pose = DockPose(0, 0, 250, 1, 0.0)
    assert assess_dock(pose, now=0.1, target_distance_mm=100,
                       max_age_seconds=0.1).phase == "approach"
    assert assess_dock(pose, now=0.15, target_distance_mm=100,
                       max_age_seconds=0.1).phase == "hold"


@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("elapsed_ms, valid", [(19, True), (20, True), (20.01, False)])
def test_beacon_age_boundary_includes_transport(side, elapsed_ms, valid):
    code = dock_beacon_code(1)
    reading = {
        "robot_id": "robot-01", "left_valid": True, "right_valid": True,
        "match": True, "left_seq": 1, "right_seq": 1,
        "left_age_ms": 100, "right_age_ms": 100, "code": code,
        "motor_authorized": False, "charging_authorized": False,
        "physical_qualified": False,
    }
    reading[f"{side}_age_ms"] = 180
    if valid:
        assert validate_ir(reading, "robot-01", elapsed_ms=elapsed_ms) == reading
    else:
        with pytest.raises(ValueError, match="Fresh NEC"):
            validate_ir(reading, "robot-01", elapsed_ms=elapsed_ms)


@pytest.mark.parametrize("age, fresh", [
    (math.nextafter(0.0, -1.0), False),
    (0.0, True),
    (0.2, True),
    (math.nextafter(0.2, math.inf), False),
])
def test_camera_receipt_age_matches_pose_assessment(monkeypatch, age, fresh):
    monkeypatch.setattr(dock_runtime, "time", SimpleNamespace(monotonic=lambda: age))
    receipt = (b"jpeg", 0.0)
    if fresh:
        assert dock_runtime.unpack_dock_frame(receipt) == receipt
    else:
        with pytest.raises(ValueError, match="Invalid or stale dock camera receipt"):
            dock_runtime.unpack_dock_frame(receipt)


def test_camera_source_verifier_requires_time_remaining(monkeypatch):
    class Head:
        async def dock_receipt_current(self, observation):
            raise AssertionError("Expired frame must not reach source verifier")

    monkeypatch.setattr(dock_runtime, "time", SimpleNamespace(monotonic=lambda: 0.2))
    receipt = (b"jpeg", 0.0, (1, 1, 1), 1)
    with pytest.raises(ValueError, match="Invalid or stale dock camera receipt"):
        asyncio.run(dock_runtime.verify_selected_dock_frame(Head(), receipt))
