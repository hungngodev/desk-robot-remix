"""Motion/037: command acknowledgments are not measured odometry."""

import pytest
from desk_robot.spatial_pose import PoseError, PoseFence


def receipt(seq, *, origin=3, quality="valid", x_mm=25, y_mm=-30, **extra):
    return {
        "robot_id": "robot-01",
        "v": 1,
        "body_boot": 9,
        "head_boot": 12,
        "origin": origin,
        "seq": seq,
        "sample_us": 1_000_000 + seq * 100_000,
        "x_mm": x_mm,
        "y_mm": y_mm,
        "yaw_mrad": 0,
        "quality": quality,
        **extra,
    }


@pytest.mark.parametrize(
    "command",
    [
        {"left": 20, "right": 20},
        {"pwm_left": 51, "pwm_right": 51},
        {"rate_milli_steps_per_second": 80_000},
        {"commanded_velocity_mm_s": 100},
    ],
)
def test_motor_command_fields_cannot_replace_encoder_pose(command):
    fence = PoseFence("robot-01")
    fence.observe(receipt(1), 100.1)
    prior = fence.observe(receipt(2), 100.2)
    assert fence.current(100.2) is prior

    # Even a fresh, correctly addressed envelope cannot launder a drive
    # command into a new metric receipt, or keep the old receipt usable.
    with pytest.raises(PoseError, match="Unexpected pose field"):
        fence.observe(receipt(3, x_mm=50, **command), 100.3)
    assert fence.current(100.3) is None
    assert not fence.owns_continuous_receipt(prior)
    assert fence.needs_reanchor


def test_stalled_wheels_and_absent_wheels_are_distinct_pose_evidence():
    fence = PoseFence("robot-01")
    fence.observe(receipt(1), 100.1)
    prior = fence.observe(receipt(2), 100.2)
    assert fence.current(100.2) is prior

    # Fresh stationary measured pose is valid, but it adds no travel.
    still = fence.observe(receipt(3), 100.3)
    assert fence.current(100.3) is still
    assert (still.x_mm, still.y_mm, still.yaw_mrad) == (
        prior.x_mm, prior.y_mm, prior.yaw_mrad
    )

    # Missing encoders produce the canonical unavailable, zero-origin body
    # diagnostic. Those zeros are not a measured return to the origin.
    for seq in range(4, 7):
        packet = receipt(seq, origin=0, quality="unavailable", x_mm=0, y_mm=0)
        if seq == 4:
            with pytest.raises(PoseError, match="re-anchor required"):
                fence.observe(packet, 100 + seq / 10)
        else:
            diagnostic = fence.observe(packet, 100 + seq / 10)
            assert diagnostic.quality == "unavailable"
        assert fence.current(100 + seq / 10) is None
        assert not fence.owns_continuous_receipt(still)
        assert fence.needs_reanchor

    # New packet clocks cannot resurrect the retired measured origin.
    with pytest.raises(PoseError, match="Retired"):
        fence.observe(receipt(7), 100.7)
    assert fence.current(100.7) is None
