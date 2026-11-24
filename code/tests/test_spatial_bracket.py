from dataclasses import replace

import pytest
from desk_robot.spatial_bracket import BracketError, validate_stationary_bracket
from desk_robot.spatial_pose import PoseFence


def fixture():
    fence = PoseFence("robot-01")
    packet = {
        "robot_id": "robot-01", "v": 1, "body_boot": 9, "origin": 3,
        "seq": 1, "sample_us": 1_000_000, "x_mm": 25, "y_mm": -30,
        "yaw_mrad": 1000, "quality": "valid", "head_boot": 12,
    }
    fence.observe(packet, 100.0, request_started_at=99.99)
    before = fence.observe(
        dict(packet, seq=2, sample_us=1_100_000), 100.1,
        request_started_at=100.09,
    )
    after = fence.observe(
        dict(packet, seq=3, sample_us=1_300_000), 100.3,
        request_started_at=100.27,
    )
    return {
        "fence": fence, "before": before, "after": after,
        "previous_camera": (12, 7, 9000), "camera": (12, 8, 10000),
        "camera_received_at": 100.2,
        "stream_generation_before": 1, "stream_generation_after": 1,
        "motion_epoch_before": 4, "motion_epoch_after": 4,
        "disarmed_before": True, "disarmed_after": True,
        "now": 100.31, "max_optical_lag_s": 0.05, "max_body_lag_s": 0.05,
    }


def test_stationary_bracket_uses_mac_elapsed_times_not_device_epochs():
    kwargs = fixture()
    result = validate_stationary_bracket(**kwargs)
    assert result.robot_id == "robot-01"
    assert (result.body_boot, result.origin) == (9, 3)
    assert result.camera_identity == (12, 8, 10000)
    assert (result.before_seq, result.after_seq) == (2, 3)
    assert result.earliest_image_at == pytest.approx(100.15)
    assert result.latest_image_at == 100.2
    assert result.odom_base.yaw_rad == 1.0
    assert kwargs["fence"].needs_reanchor


@pytest.mark.parametrize("updates", [
    {"camera": (13, 8, 10000)},
    {"camera": (12, 7, 10000)},
    {"camera": (12, 8, 9000)},
    {"camera": (12, True, 10000)},
    {"previous_camera": (11, 7, 9000)},
    {"stream_generation_after": 2},
    {"motion_epoch_after": 5},
    {"motion_epoch_after": True},
    {"disarmed_before": False},
    {"disarmed_after": 1},
    {"now": 101.0},
    {"camera_received_at": 100.12},
    {"camera_received_at": 100.29},
    {"max_optical_lag_s": 0},
    {"max_optical_lag_s": float("nan")},
    {"max_body_lag_s": 0.001},
    {"max_body_lag_s": 10**400},
])
def test_bad_bracket_rejected(updates):
    kwargs = fixture()
    kwargs.update(updates)
    with pytest.raises(BracketError):
        validate_stationary_bracket(**kwargs)


@pytest.mark.parametrize("updates", [
    {"robot_id": "robot-02"}, {"body_boot": 10}, {"origin": 4},
    {"head_boot": 13}, {"seq": 3}, {"sample_us": 1_300_000},
    {"quality": "degraded"}, {"x_mm": 26}, {"yaw_mrad": 1001},
    {"request_started_at": None},
])
def test_before_pose_must_match_stationary_body_and_camera(updates):
    kwargs = fixture()
    kwargs["before"] = replace(kwargs["before"], **updates)
    with pytest.raises(BracketError):
        validate_stationary_bracket(**kwargs)


def test_later_pose_or_pickup_invalidates_selected_bracket():
    kwargs = fixture()
    kwargs["fence"].invalidate("pickup")
    with pytest.raises(BracketError, match="current"):
        validate_stationary_bracket(**kwargs)
