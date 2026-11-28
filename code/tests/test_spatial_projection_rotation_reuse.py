"""Pitch and yaw use the same signed plane rotation without moving safety gates."""

import math

import pytest
from desk_robot import spatial_projection
from desk_robot.dock_vision import DockCameraCalibration
from desk_robot.spatial_frames import rotate_xy


@pytest.mark.parametrize("pitch,yaw", [(15, -15), (30, 15), (60, 0)])
def test_projection_reuses_rotation_for_both_planes(monkeypatch, pitch, yaw):
    lens = DockCameraCalibration(
        400, 400, 320, 240, 50, 4, (0.0,) * 5, 640, 480, "OV5640", 11, yaw,
    )
    cal = spatial_projection.FloorProjectionCalibration(
        lens, "rotation-test", 100, 23, pitch, (0, 0, 640, 480),
        (-1000, 1000), (-1000, 1000), 10, measured=True,
    )
    calls = []

    def track_rotation(x, y, angle):
        calls.append((x, y, angle))
        return rotate_xy(x, y, angle)

    monkeypatch.setattr(spatial_projection, "rotate_xy", track_rotation)
    result = cal.project(440, 320, image_width=640, image_height=480,
                         camera_sensor_pid="OV5640")
    p, a = math.radians(pitch), math.radians(yaw)
    # Independent pitch/yaw equations preserve the signed camera convention.
    ray_x = math.cos(p) - 0.2 * math.sin(p)
    ray_z = -math.sin(p) - 0.2 * math.cos(p)
    scale = 100 / -ray_z
    assert result.x_mm == pytest.approx(23 + scale * (ray_x * math.cos(a) - 0.3 * math.sin(a)))
    assert result.y_mm == pytest.approx(-11 + scale * (-ray_x * math.sin(a) - 0.3 * math.cos(a)))
    assert len(calls) == 2
    assert calls[0] == pytest.approx((1.0, -0.2, -p))
    assert calls[1] == pytest.approx((ray_x, -0.3, -a))
