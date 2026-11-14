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


def test_dock_vision_rejects_nonnumeric_timing_without_loading_cv2():
    for value in (None, "1", True, float("inf")):
        with pytest.raises(ValueError):
            detect_apriltag(b"jpeg", calibration(), captured_at=value)
        with pytest.raises(ValueError):
            detect_apriltag(b"jpeg", calibration(), captured_at=1,
                            max_reprojection_error_px=value)


def test_distortion_coefficients_are_validated_without_motion_authority():
    from dataclasses import replace

    base = calibration()
    assert replace(base, distortion_coeffs=(0.1, -0.05, 0.001, 0.002, 0.0)).distortion_coeffs[0] == 0.1
    for invalid in ((1.0,), (0.0, 0.0, float("nan"), 0.0),
                    (0.0, 0.0, True, 0.0), [0.0] * 5):
        with pytest.raises(ValueError):
            replace(base, distortion_coeffs=invalid)
    assessment = assess_dock(DockPose(0, 0, 300, 0.5, 1),
                             now=1.1, target_distance_mm=120)
    assert not assessment.motor_authorized and not assessment.charging_authorized




@pytest.mark.parametrize(("width", "height"), [
    (640, None), (None, 480), (True, 480),
    (640, "480"), (79, 480), (640, 1600),
])
def test_dock_calibration_refuses_incomplete_or_invalid_image_mode(width, height):
    from dataclasses import replace
    with pytest.raises(ValueError):
        replace(calibration(), image_width_px=width, image_height_px=height)


def test_dock_detector_rejects_camera_mode_change_before_apriltag_pose():
    """Matching distortion and focal lengths are invalid at another JPEG size."""
    import cv2
    import numpy as np
    from dataclasses import replace

    measured = replace(
        calibration(), image_width_px=640, image_height_px=480,
        distortion_coeffs=(0.18, -0.07, 0.003, -0.002, 0.01),
    )
    ok, jpeg = cv2.imencode(".jpg", np.zeros((240, 320), dtype=np.uint8))
    assert ok
    with pytest.raises(ValueError, match="resolution differs"):
        detect_apriltag(jpeg.tobytes(), measured, captured_at=5.0)


def test_measured_distortion_recovers_synthetic_apriltag_pose(monkeypatch):
    """Exercise the real OpenCV PnP path with projected distorted corners.

    This is synthetic geometry, not a calibrated XIAO camera or dock trial.
    """
    import cv2
    import numpy as np

    distortion = (0.18, -0.07, 0.003, -0.002, 0.01)
    camera = DockCameraCalibration(
        fx=410, fy=410, cx=320, cy=240, tag_side_mm=60,
        marker_id=12, distortion_coeffs=distortion,
        image_width_px=640, image_height_px=480,
    )
    half = camera.tag_side_mm / 2
    object_points = np.array([
        [-half, half, 0], [half, half, 0],
        [half, -half, 0], [-half, -half, 0],
    ], dtype=np.float64)
    intrinsics = np.array([
        [camera.fx, 0, camera.cx], [0, camera.fy, camera.cy],
        [0, 0, 1],
    ], dtype=np.float64)
    rotation = np.array([[0.08], [-0.04], [0.03]])
    translation = np.array([[14.0], [-8.0], [380.0]])
    corners, _ = cv2.projectPoints(
        object_points, rotation, translation, intrinsics,
        np.asarray(distortion, dtype=np.float64),
    )

    class SyntheticDetector:
        def __init__(self, dictionary):
            pass

        def detectMarkers(self, frame):
            return [corners.astype(np.float32).reshape(1, 4, 2)], np.array([[12]]), []

    monkeypatch.setattr(cv2.aruco, "ArucoDetector", SyntheticDetector)
    ok, jpeg = cv2.imencode(".jpg", np.zeros((480, 640), dtype=np.uint8))
    assert ok
    pose = detect_apriltag(jpeg.tobytes(), camera, captured_at=5.0)
    assert pose is not None
    assert abs(pose.x_mm - 14.0) < 0.1
    assert abs(pose.y_mm + 8.0) < 0.1
    assert abs(pose.z_mm - 380.0) < 0.5
    assert pose.reprojection_error_px < 0.1
    assessment = assess_dock(pose, now=5.1, target_distance_mm=120)
    assert assessment.phase == "approach"
    assert assessment.motor_authorized is False
    assert assessment.charging_authorized is False
