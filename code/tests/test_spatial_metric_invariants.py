"""Synthetic metric geometry checks; no physical qualification or motion authority."""
import cmath
import math
from dataclasses import replace
from itertools import product

import pytest
from desk_robot.dock_vision import DockCameraCalibration
from desk_robot.spatial_frames import PlanarTransform, map_odom_transform
from desk_robot.spatial_projection import FloorProjectionCalibration, ProjectionError


def lens(**changes):
    base = DockCameraCalibration(
        410, 405, 320, 240, 60, 12,
        distortion_coeffs=(0.0,) * 5, image_width_px=640, image_height_px=480,
        camera_sensor_pid="OV5640", mount_lateral_offset_mm=13, mount_yaw_deg=0,
    )
    return replace(base, **changes)


@pytest.mark.parametrize(("field", "value"), [
    ("fx", 0.001), ("fx", 63.99), ("fx", 6400.01),
    ("fy", 0.001), ("fy", 47.99), ("fy", 4800.01),
])
def test_runtime_focal_lengths_match_calibration_fitter_envelope(field, value):
    with pytest.raises(ValueError, match="focal lengths"):
        lens(**{field: value})


@pytest.mark.parametrize(("fx", "fy"), [(64, 48), (6400, 4800)])
def test_runtime_focal_length_envelope_is_inclusive(fx, fy):
    assert lens(fx=fx, fy=fy).fx == fx


@pytest.mark.parametrize("yaw", [-20, 0, 20])
@pytest.mark.parametrize("pitch", [25, 35, 50])
@pytest.mark.parametrize("distorted", [False, True])
def test_camera_floor_odom_map_chain(yaw, pitch, distorted):
    np = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    coeffs = (-0.08, 0.01, 0.001, -0.002, 0.0) if distorted else (0.0,) * 5
    camera = lens(mount_yaw_deg=yaw, distortion_coeffs=coeffs)
    cal = FloorProjectionCalibration(
        camera, "synthetic", 100, 17, pitch, (0, 0, 640, 480),
        (-1000, 1000), (-1000, 1000), 5, measured=True,
    )
    # Independently compose proper 3D rotations with OpenCV Rodrigues.
    # Optical x right, y down, z forward -> base x forward, y left, z up.
    optical_to_base = np.array([[0., 0., 1.], [-1., 0., 0.], [0., -1., 0.]])
    tilt, _ = cv2.Rodrigues(np.array([0., math.radians(pitch), 0.]))
    heading, _ = cv2.Rodrigues(np.array([0., 0., -math.radians(yaw)]))
    rotation = heading @ tilt @ optical_to_base
    assert np.linalg.det(rotation) == pytest.approx(1.0)
    origin = np.array([17., -13., 100.])
    k = np.array([[410., 0., 320.], [0., 405., 240.], [0., 0., 1.]])
    odom = PlanarTransform("odom", "base_link", 123, -67, 0.73)
    anchor = PlanarTransform("map", "odom", -190, 290, -1.14)
    chain = anchor.compose(odom)
    for x, y in product(np.linspace(-0.3, 0.3, 5), np.linspace(-0.2, 0.2, 5)):
        optical_ray = np.array([x, y, 1.])
        direction = rotation @ optical_ray
        ground = origin - (origin[2] / direction[2]) * direction
        pixels, _ = cv2.projectPoints(
            optical_ray.reshape(1, 3), np.zeros(3), np.zeros(3), k, np.array(coeffs),
        )
        u, v = map(float, pixels.reshape(2))
        point = cal.project(u, v, image_width=640, image_height=480,
                            camera_sensor_pid="OV5640")
        assert (point.x_mm, point.y_mm) == pytest.approx(tuple(ground[:2]), abs=0.01)
        assert point.frame == "base_link"
        expected = complex(-190, 290) + cmath.exp(-1.14j) * (
            complex(123, -67) + cmath.exp(0.73j) * complex(*ground[:2])
        )
        assert chain.point(point.x_mm, point.y_mm) == pytest.approx(
            (expected.real, expected.imag), abs=0.01,
        )


def test_planar_transform_composition_inverse_and_reanchor_sweep():
    angles = [math.pi * i / 8 for i in range(-8, 9)]
    for a, b in product(angles, repeat=2):
        first = PlanarTransform("map", "odom", 125, -84, a)
        second = PlanarTransform("odom", "base_link", -210, 37, b)
        combined = first.compose(second)
        recovered = map_odom_transform(combined, second)
        for point in [(0, 0), (100, -250), (-850, 640)]:
            expected = complex(125, -84) + cmath.exp(1j * a) * (
                complex(-210, 37) + cmath.exp(1j * b) * complex(*point)
            )
            actual = combined.point(*point)
            assert actual == pytest.approx((expected.real, expected.imag), abs=1e-9)
            assert combined.inverse().point(*actual) == pytest.approx(point, abs=1e-9)
            assert recovered.point(*point) == pytest.approx(first.point(*point), abs=1e-9)


@pytest.mark.parametrize(("u", "v"), [(-0.001, 240), (640, 240), (320, 480), (320, -0.001)])
def test_projection_does_not_clamp_off_image_pixels(u, v):
    cal = FloorProjectionCalibration(
        lens(), "synthetic", 100, 17, 35, (0, 0, 640, 480),
        (-1000, 1000), (-1000, 1000), 5, measured=True,
    )
    with pytest.raises(ProjectionError, match="crop"):
        cal.project(u, v, image_width=640, image_height=480, camera_sensor_pid="OV5640")
