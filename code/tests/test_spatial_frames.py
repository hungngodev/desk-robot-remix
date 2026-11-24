import math

import pytest
from desk_robot.spatial_frames import (
    FrameError,
    PlanarTransform,
    map_odom_transform,
    odom_base_transform,
)
from desk_robot.spatial_pose import decode_pose


def test_positive_rotation_and_inverse():
    transform = PlanarTransform("map", "odom", 100, 50, math.pi / 2)
    assert transform.point(20, 0) == pytest.approx((100, 70))
    assert transform.inverse().point(100, 70) == pytest.approx((20, 0))
    assert transform.compose(transform.inverse()) == PlanarTransform(
        "map", "map", 0, 0, 0,
    )


@pytest.mark.parametrize("trial", range(10))
def test_reanchor_replay_preserves_continuous_body_pose(trial):
    # Synthetic measured-location inputs, independently generated from a
    # cardinal rotation and a translated origin. Not physical error trials.
    odom = PlanarTransform("odom", "base_link", 20 + trial, -30 + trial, 0)
    initial = PlanarTransform("map", "base_link", 20 + trial, -30 + trial, 0)
    first = map_odom_transform(initial, odom)
    assert first.point(0, 0) == pytest.approx((0, 0))
    measured = PlanarTransform(
        "map", "base_link", 200 - odom.y_mm, 80 + odom.x_mm, math.pi / 2,
    )
    corrected = map_odom_transform(measured, odom)
    assert corrected.point(0, 0) == pytest.approx((200, 80))
    assert corrected.yaw_rad == pytest.approx(math.pi / 2)
    actual = corrected.compose(odom)
    assert (actual.x_mm, actual.y_mm, actual.yaw_rad) == pytest.approx(
        (measured.x_mm, measured.y_mm, measured.yaw_rad),
    )
    assert odom == PlanarTransform("odom", "base_link", 20 + trial, -30 + trial, 0)
    # A subsequent +10 mm local step is continuous even after correction.
    next_odom = PlanarTransform("odom", "base_link", odom.x_mm + 10, odom.y_mm, 0)
    next_map = corrected.compose(next_odom)
    assert (next_map.x_mm, next_map.y_mm) == pytest.approx(
        (measured.x_mm, measured.y_mm + 10),
    )


def test_typed_receipt_units_and_wrapped_yaw():
    packet = {
        "robot_id": "robot-01", "v": 1, "body_boot": 9, "origin": 3,
        "seq": 1, "sample_us": 100, "x_mm": 25, "y_mm": -30,
        "yaw_mrad": 3142, "quality": "valid", "head_boot": 12,
    }
    receipt = decode_pose(packet, "robot-01", 100.0)
    transform = odom_base_transform(receipt)
    assert (transform.x_mm, transform.y_mm) == (25, -30)
    assert transform.yaw_rad == pytest.approx(3.142 - math.tau)
    packet["quality"] = "degraded"
    with pytest.raises(FrameError):
        odom_base_transform(decode_pose(packet, "robot-01", 100.0))


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, 10**400, "20"])
def test_invalid_transform_numbers_rejected(bad):
    with pytest.raises(FrameError):
        PlanarTransform("map", "odom", bad, 0, 0)


def test_bad_frames_cycles_and_bounds_rejected():
    a = PlanarTransform("map", "odom", 10, 0, 0)
    with pytest.raises(FrameError):
        a.compose(a)
    with pytest.raises(FrameError):
        a.compose(PlanarTransform("odom", "map", 10, 0, 0))
    with pytest.raises(FrameError):
        map_odom_transform(a, a)
    with pytest.raises(FrameError):
        PlanarTransform("map", "other", 0, 0, 0)
    with pytest.raises(FrameError):
        PlanarTransform("map", "map", 1, 0, 0)
    with pytest.raises(FrameError):
        a.point(1_000_000, 0)
