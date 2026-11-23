from dataclasses import replace

import pytest
from desk_robot.dock_vision import DockCameraCalibration
from desk_robot.spatial_projection import FloorProjectionCalibration, ProjectionError


def calibration(**overrides):
    lens = DockCameraCalibration(
        fx=400, fy=400, cx=320, cy=240, tag_side_mm=50, marker_id=4,
        distortion_coeffs=(0.0, 0.0, 0.0, 0.0, 0.0),
        image_width_px=640, image_height_px=480,
        camera_sensor_pid="OV5640", mount_lateral_offset_mm=0,
        mount_yaw_deg=0,
    )
    return FloorProjectionCalibration(
        lens=lens, calibration_id="sample-cal-1", camera_height_mm=100,
        camera_forward_offset_mm=0, pitch_down_deg=30,
        valid_pixel_roi=(0, 0, 640, 480), valid_forward_mm=(-1000, 1000),
        valid_lateral_mm=(-1000, 1000), uncertainty_mm=10,
        measured=True, **overrides,
    )


def project(cal, u, v):
    return cal.project(u, v, image_width=640, image_height=480,
                       camera_sensor_pid="OV5640")


def test_optical_center_hits_measured_floor_and_positive_ray_directions():
    cal = calibration()
    center = project(cal, 320, 240)
    assert center.x_mm == pytest.approx(173.2050807569)
    assert center.y_mm == pytest.approx(0)
    right = project(cal, 420, 240)
    assert right.x_mm == pytest.approx(center.x_mm)
    assert right.y_mm == pytest.approx(-50)
    down = project(cal, 320, 320)
    assert down.x_mm < center.x_mm
    assert down.y_mm == pytest.approx(0)


def test_mount_yaw_right_rotates_forward_ray_towards_negative_y():
    cal = calibration()
    # Keep the positive yaw fixture inside DockCameraCalibration's measured
    # mount envelope, rather than bypassing the production +/-20 degree gate.
    new_lens = replace(cal.lens, mount_yaw_deg=15)
    rotated = project(replace(cal, lens=new_lens), 320, 240)
    assert rotated.x_mm == pytest.approx(167.3032607476, abs=0.01)
    assert rotated.y_mm == pytest.approx(-44.8287736084, abs=0.01)


def test_mount_yaw_outside_measured_limits_cannot_project():
    cal = calibration()
    with pytest.raises(ValueError, match="mount offset or yaw outside measured limits"):
        replace(cal.lens, mount_yaw_deg=45)
    with pytest.raises(ValueError, match="mount offset or yaw outside measured limits"):
        replace(cal.lens, mount_yaw_deg=-45)


def test_horizon_grazing_and_crop_rejected():
    cal = calibration()
    with pytest.raises(ProjectionError, match="grazes"):
        project(cal, 320, 9)
    with pytest.raises(ProjectionError, match="crop"):
        project(replace(cal, valid_pixel_roi=(100, 100, 540, 400)), 10, 200)
    with pytest.raises(ProjectionError, match="floor region"):
        project(replace(cal, valid_forward_mm=(0, 100)), 320, 240)


def test_camera_identity_and_resolution_are_strict():
    cal = calibration()
    with pytest.raises(ProjectionError, match="PID or resolution"):
        cal.project(320, 240, image_width=320, image_height=240,
                    camera_sensor_pid="OV5640")
    with pytest.raises(ProjectionError, match="PID or resolution"):
        cal.project(320, 240, image_width=640, image_height=480,
                    camera_sensor_pid="OV3660")


def test_unmeasured_mount_lens_or_window_cannot_project():
    cal = calibration()
    with pytest.raises(ProjectionError, match="Actual measured"):
        project(replace(cal, measured=False), 320, 240)
    with pytest.raises(ProjectionError, match="incomplete"):
        replace(cal, lens=replace(cal.lens, distortion_coeffs=None))
    with pytest.raises(ProjectionError, match="resolution"):
        replace(cal, valid_pixel_roi=(0, 0, 700, 480))


def test_distortion_uses_opencv_when_present():
    cv2 = pytest.importorskip("cv2")
    assert cv2 is not None
    cal = calibration()
    distorted = replace(cal, lens=replace(cal.lens,
                        distortion_coeffs=(0.1, -0.03, 0.0, 0.0, 0.0)))
    result = project(distorted, 320, 240)
    assert result.x_mm == pytest.approx(173.2050807569)
