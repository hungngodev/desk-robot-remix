"""Docking cannot gain motion or charger authority from image geometry."""
import math

import pytest
from desk_robot.dock_vision import (
    DockAssessment,
    DockCameraCalibration,
    DockPose,
    assess_dock,
    detect_apriltag,
)


def calibration():
    return DockCameraCalibration(
        fx=410, fy=410, cx=320, cy=240,
        tag_side_mm=60, marker_id=12,
    )


def test_camera_calibration_never_guesses_zero_or_nan_geometry():
    assert calibration().tag_side_mm == 60
    for value in (0, -10, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            DockCameraCalibration(value, 410, 320, 240, 60, 12)
    with pytest.raises(ValueError):
        DockCameraCalibration(410, 410, 320, 240, 0, 12)


def test_docking_assessment_never_returns_motor_or_charger_permission():
    assert assess_dock(None, now=1, target_distance_mm=120).phase == "hold"
    for x, z, error, at, phase in (
        (80, 400, 0.5, 1, "align"),
        (0, 400, 0.5, 1, "approach"),
        (0, 80, 0.5, 1, "hold"),
        (0, 400, 5.0, 1, "hold"),
        (0, 400, 0.5, 0, "hold"),
        (0, 400, 0.5, 2, "hold"),
    ):
        assessment = assess_dock(
            DockPose(x, 0, z, error, at),
            now=1.1, target_distance_mm=120,
        )
        assert assessment.phase == phase
        assert assessment.motor_authorized is False
        assert assessment.charging_authorized is False


def test_dock_pose_rejects_bad_geometry():
    for z in (0, -1, math.nan, math.inf):
        with pytest.raises(ValueError):
            DockPose(0, 0, z, 1, 1)
    assert not DockAssessment("align", "not a command").motor_authorized


def test_dock_vision_rejects_bad_frames_without_cv2_or_io():
    with pytest.raises(ValueError):
        detect_apriltag(b"", calibration(), captured_at=1)
    with pytest.raises(ValueError):
        detect_apriltag(b"hello", calibration(), captured_at=float("nan"))
