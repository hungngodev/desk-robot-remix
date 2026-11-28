import math

import pytest
from desk_robot.spatial_frames import (
    PlanarTransform,
    odom_base_transform,
    rotate_xy,
    wrap_yaw_rad,
)
from desk_robot.spatial_pose import PoseReceipt


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


@pytest.mark.parametrize("yaw_mrad", [-3142, 3142])
def test_raw_receipt_yaw_preserved_until_frame_conversion(yaw_mrad: int) -> None:
    receipt = PoseReceipt("robot-01", 9, 3, 1, 100, 25, -30, yaw_mrad, "valid", 1.0, 12)
    assert receipt.yaw_rad == yaw_mrad / 1000.0
    transform = odom_base_transform(receipt)
    expected = yaw_mrad / 1000.0 - math.copysign(math.tau, yaw_mrad)
    assert transform.yaw_rad == pytest.approx(expected)
    assert transform.point(0, 0) == pytest.approx((25, -30))
