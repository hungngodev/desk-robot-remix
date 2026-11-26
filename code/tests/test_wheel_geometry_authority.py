"""The Mac consumes metric body pose, not nominal drivetrain geometry."""

import pytest
from desk_robot.spatial_pose import PoseError, PoseFence


def receipt(seq):
    return {
        "robot_id": "robot-01",
        "v": 1,
        "body_boot": 9,
        "head_boot": 12,
        "origin": 3,
        "seq": seq,
        "sample_us": 1_000_000 + seq * 100_000,
        "x_mm": 96,
        "y_mm": -25,
        "yaw_mrad": 500,
        "quality": "valid",
    }


@pytest.mark.parametrize(
    "geometry",
    [
        {"wheel_radius_mm": 20},
        {"track_width_mm": 96},
        {"left_nm_per_count": 100_000},
        {"right_nm_per_count": 100_000},
        {"wheelbase_mm": 96},
    ],
)
def test_nominal_geometry_cannot_override_metric_pose(geometry):
    fence = PoseFence("robot-01")
    fence.observe(receipt(1), 100.1)
    prior = fence.observe(receipt(2), 100.2)
    assert fence.current(100.2) is prior
    assert (prior.x_mm, prior.y_mm, prior.yaw_mrad) == (96, -25, 500)
    assert prior.yaw_rad == 0.5

    # Geometry belongs to the body calibration, not the pose wire schema.
    with pytest.raises(PoseError, match="Unexpected pose field"):
        fence.observe({**receipt(3), **geometry}, 100.3)
    assert fence.current(100.3) is None
    assert not fence.owns_continuous_receipt(prior)
    assert fence.needs_reanchor
