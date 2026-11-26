"""Parity between the shared measured lens and its two geometry consumers."""
from dataclasses import replace
from io import BytesIO

import pytest
from PIL import Image

from desk_robot.dock_vision import DockCameraCalibration, detect_apriltag
from desk_robot.spatial_projection import FloorProjectionCalibration


@pytest.mark.parametrize("count", [4, 5, 8, 12, 14])
def test_opencv_parameters_preserve_intrinsics_and_distortion_order(count):
    coefficients = tuple(i / 1000 for i in range(count))
    lens = DockCameraCalibration(410, 380, 301, 217, 60, 12, coefficients)
    assert lens.opencv_parameters() == (
        ((410, 0, 301), (0, 380, 217), (0, 0, 1)), coefficients,
    )
    assert replace(lens, distortion_coeffs=None).opencv_parameters()[1] == (0.0,) * 5


def test_shared_lens_preserves_dock_pose_and_off_axis_floor_projection(monkeypatch):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    if not hasattr(cv2, "aruco") or not hasattr(cv2.aruco, "ArucoDetector"):
        pytest.skip("OpenCV AprilTag detector unavailable")
    coefficients = (0.10, -0.03, 0.002, -0.004, 0.01)
    lens = DockCameraCalibration(
        410, 380, 301, 217, 60, 12, coefficients, 640, 480, "OV5640", 0, 0,
    )
    # Independent reference matrix: do not generate expected observations
    # with the helper being tested, or a swapped focal axis could pass.
    k = np.array([[410., 0., 301.], [0., 380., 217.], [0., 0., 1.]])
    d = np.array(coefficients)
    square = np.array([[-30., 30., 0.], [30., 30., 0.],
                       [30., -30., 0.], [-30., -30., 0.]])
    corners, _ = cv2.projectPoints(
        square, np.array([3.05, 0.12, 0.05]), np.array([40., 20., 300.]), k, d,
    )

    class Detector:
        def detectMarkers(self, frame):
            return [corners.reshape(1, 4, 2)], np.array([[12]]), []

    monkeypatch.setattr(cv2.aruco, "ArucoDetector", lambda dictionary: Detector())
    jpeg = BytesIO()
    Image.new("L", (640, 480), 128).save(jpeg, format="JPEG")
    calls = []
    original = DockCameraCalibration.opencv_parameters

    def tracked(calibration):
        calls.append(calibration)
        return original(calibration)

    monkeypatch.setattr(DockCameraCalibration, "opencv_parameters", tracked)
    pose = detect_apriltag(jpeg.getvalue(), lens, captured_at=1.0)
    assert pose is not None
    assert (pose.x_mm, pose.y_mm, pose.z_mm) == pytest.approx((40, 20, 300), abs=0.01)

    floor = FloorProjectionCalibration(
        lens, "shared-lens", 100, 0, 30, (0, 0, 640, 480),
        (-1000, 1000), (-1000, 1000), 10, measured=True,
    )
    pixel, _ = cv2.projectPoints(
        np.array([[0.45, 0.25, 1.0]]), np.zeros(3), np.zeros(3), k, d,
    )
    u, v = pixel[0, 0]
    point = floor.project(float(u), float(v), image_width=640, image_height=480,
                          camera_sensor_pid="OV5640")
    assert (point.x_mm, point.y_mm) == pytest.approx((103.4220286821, -62.8047468673), abs=0.01)
    assert calls == [lens, lens]
