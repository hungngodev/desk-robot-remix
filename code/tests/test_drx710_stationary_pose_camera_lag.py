import pytest

from desk_robot.spatial_bracket import BracketError, validate_stationary_bracket
from desk_robot.spatial_pose import PoseFence


@pytest.mark.parametrize(
    ("fault", "reason"),
    [
        ("none", None),
        ("stale_before", "source freshness"),
        ("stale_middle", "source freshness"),
        ("moving", "changed odometry"),
        ("motion_epoch", "Motion or pickup epoch"),
        ("armed", "Motion or pickup epoch"),
        ("early_jpeg", "possible image time"),
        ("late_jpeg", "possible image time"),
    ],
)
def test_stationary_bracket_rejects_unqualified_pair(fault, reason):
    fence = PoseFence("robot-01")
    packet = {
        "robot_id": "robot-01", "v": 1, "head_boot": 77,
        "body_boot": 8, "origin": 3, "x_mm": 25, "y_mm": -30,
        "yaw_mrad": 1000, "quality": "valid",
    }

    def observe(seq, at, sample_us, **overrides):
        return fence.observe(
            dict(packet, seq=seq, sample_us=sample_us, **overrides),
            at, request_started_at=at - 0.01,
        )

    observe(1, 100.0, 1_000_000)
    before = observe(2, 100.1, 1_020_000 if fault == "stale_before" else 1_100_000)
    observe(3, 100.2, 1_120_000 if fault == "stale_middle" else 1_200_000,
            x_mm=26 if fault == "moving" else 25)
    after = observe(4, 100.3, 1_300_000)
    assert fence.current(100.3) is after
    kwargs = dict(
        fence=fence, before=before, after=after,
        previous_camera=(77, 1, 10_000), camera=(77, 2, 20_000),
        camera_received_at={"early_jpeg": 100.12, "late_jpeg": 100.29}.get(fault, 100.2),
        stream_generation_before=1, stream_generation_after=1,
        motion_epoch_before=4, motion_epoch_after=5 if fault == "motion_epoch" else 4,
        disarmed_before=fault != "armed", disarmed_after=True,
        now=100.3, max_optical_lag_s=0.05, max_body_lag_s=0.05,
    )
    if reason is None:
        assert validate_stationary_bracket(**kwargs).camera_identity == (77, 2, 20_000)
    else:
        with pytest.raises(BracketError, match=reason):
            validate_stationary_bracket(**kwargs)
    assert fence.needs_reanchor
