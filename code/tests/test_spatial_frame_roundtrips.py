import cmath
import math

import pytest
from desk_robot.spatial_frames import (
    PlanarTransform,
    map_odom_transform,
    odom_base_transform,
)
from desk_robot.spatial_pose import PoseFence


@pytest.mark.parametrize("yaw_mrad", [-3142, -2356, -1571, -785, 0, 785, 1571, 2356, 3142])
@pytest.mark.parametrize("x_sign,y_sign", [(1, 1), (-1, 1), (-1, -1), (1, -1)])
def test_signed_receipt_and_reanchor_round_trip(yaw_mrad, x_sign, y_sign):
    packet = {
        "robot_id": "robot-01", "v": 1, "body_boot": 9, "origin": 3,
        "seq": 1, "sample_us": 1_000_000, "x_mm": x_sign * 137,
        "y_mm": y_sign * 83, "yaw_mrad": yaw_mrad, "quality": "valid", "head_boot": 12,
    }
    fence = PoseFence("robot-01")
    fence.observe(packet, 10.0)
    packet.update(seq=2, sample_us=1_100_000)
    receipt = fence.observe(packet, 10.1)
    assert fence.current(10.1) is receipt
    odom = odom_base_transform(receipt)
    translation = complex(packet["x_mm"], packet["y_mm"])
    rotation = cmath.rect(1, yaw_mrad / 1000)
    correction = PlanarTransform("map", "odom", -231, 179, -1.13)
    map_rotation = cmath.rect(1, -1.13)
    map_translation = complex(-231, 179)
    composed = correction.compose(odom)
    recovered = map_odom_transform(composed, odom)
    assert (recovered.x_mm, recovered.y_mm, recovered.yaw_rad) == pytest.approx(
        (-231, 179, -1.13), abs=1e-9,
    )
    for point in (complex(31, 19), complex(-31, 19), complex(-31, -19), complex(31, -19)):
        expected_odom = translation + rotation * point
        expected_map = map_translation + map_rotation * expected_odom
        local = odom.point(point.real, point.imag)
        world = composed.point(point.real, point.imag)
        assert local == pytest.approx((expected_odom.real, expected_odom.imag), abs=1e-9)
        assert world == pytest.approx((expected_map.real, expected_map.imag), abs=1e-9)
        assert correction.point(*local) == pytest.approx(world, abs=1e-9)
        assert composed.inverse().point(*world) == pytest.approx(
            (point.real, point.imag), abs=1e-9,
        )
        assert odom.inverse().point(*correction.inverse().point(*world)) == pytest.approx(
            (point.real, point.imag), abs=1e-9,
        )
    assert odom.compose(odom.inverse()) == PlanarTransform("odom", "odom", 0, 0, 0)
    assert odom.inverse().compose(odom) == PlanarTransform("base_link", "base_link", 0, 0, 0)
    assert math.cos(odom.yaw_rad) == pytest.approx(rotation.real, abs=1e-12)
    assert math.sin(odom.yaw_rad) == pytest.approx(rotation.imag, abs=1e-12)
    assert fence.needs_reanchor
    assert fence.current(10.1) is receipt
