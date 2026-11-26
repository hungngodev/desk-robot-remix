import math

import pytest

from desk_robot.spatial_frames import PlanarTransform, rotate_xy, wrap_yaw_rad


@pytest.mark.parametrize(("angle", "expected"), [
    (math.pi, math.pi), (-math.pi, -math.pi),
    (3 * math.pi, -math.pi), (-3 * math.pi, math.pi),
    (3.142, 3.142 - math.tau), (-3.142, math.tau - 3.142),
    (math.tau, 0.0),
])
def test_wrap_yaw_rad_endpoints(angle: float, expected: float) -> None:
    assert wrap_yaw_rad(angle) == pytest.approx(expected)


@pytest.mark.parametrize(("angle", "expected"), [
    (math.pi / 2, (-4, 3)), (-math.pi / 2, (4, -3)),
    (math.pi, (-3, -4)), (0.0, (3, 4)),
])
def test_rotate_xy_axes(angle: float, expected: tuple[int, int]) -> None:
    assert rotate_xy(3, 4, angle) == pytest.approx(expected)


@pytest.mark.parametrize("angle", [-math.pi, -0.3, 0.0, 0.3, math.pi])
def test_transform_round_trip(angle: float) -> None:
    transform = PlanarTransform("map", "odom", 40, -70, angle)
    assert transform.inverse().point(*transform.point(100, 200)) == pytest.approx((100, 200))
    assert transform.compose(transform.inverse()) == PlanarTransform("map", "map", 0, 0, 0)
