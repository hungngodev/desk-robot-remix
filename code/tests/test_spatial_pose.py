import copy

import pytest
from desk_robot.spatial_pose import PoseError, PoseFence, decode_pose


def pose(**changes):
    sample = {
        "robot_id": "robot-01", "v": 1, "body_boot": 9, "origin": 3,
        "seq": 1, "sample_us": 1_000_000, "x_mm": 25, "y_mm": -30,
        "yaw_mrad": 1571, "quality": "valid", "head_boot": 12,
    }
    sample.update(changes)
    return sample


def test_typed_mm_and_positive_rotation_and_first_sample_cannot_plan():
    gate = PoseFence("robot-01")
    first = gate.observe(pose(), 100.0)
    assert first.x_mm == 25
    assert first.y_mm == -30
    assert first.yaw_rad == pytest.approx(1.571)
    assert first.head_boot == 12
    assert gate.current(100.0) is None
    second = gate.observe(pose(seq=2, sample_us=1_100_000), 100.1)
    assert gate.current(100.2) == second
    assert gate.needs_reanchor
    assert gate.blocked_reason == "unanchored"


@pytest.mark.parametrize("updates", [
    {"robot_id": "robot-02"}, {"robot_id": None}, {"v": 2},
    {"v": True}, {"seq": 0}, {"seq": True}, {"sample_us": -1},
    {"sample_us": (1 << 63)}, {"body_boot": -1}, {"origin": -1},
    {"head_boot": -1}, {"quality": "excellent"},
    {"yaw_mrad": 3143}, {"x_mm": 1_000_001}, {"y_mm": -1_000_001},
    {"x_mm": 1.0}, {"head_boot": False},
])
def test_bad_pose_fields_fail_closed(updates):
    with pytest.raises(PoseError):
        decode_pose(pose(**updates), "robot-01", 100.0)


def test_no_mutation_of_input_and_optional_head_boot():
    raw = pose()
    saved = copy.deepcopy(raw)
    assert decode_pose(raw, "robot-01", 42.0).robot_id == "robot-01"
    assert raw == saved
    raw.pop("head_boot")
    assert decode_pose(raw, "robot-01", 42.0).head_boot is None


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, True, "10"])
def test_invalid_receipt_clock_rejected(bad):
    with pytest.raises(PoseError):
        decode_pose(pose(), "robot-01", bad)


@pytest.mark.parametrize("updates", [
    {"seq": 1, "sample_us": 1_100_000},
    {"seq": 2, "sample_us": 1_000_000},
    {"seq": 2, "sample_us": 900_000},
])
def test_duplicate_or_clock_reset_quarantines_origin(updates):
    gate = PoseFence("robot-01")
    gate.observe(pose(), 100)
    with pytest.raises(PoseError):
        gate.observe(pose(**updates), 100.1)
    assert gate.current(100.1) is None
    with pytest.raises(PoseError, match="Retired or failed"):
        gate.observe(pose(seq=3, sample_us=2_000_000), 100.2)


def test_missing_pose_and_reboot_requires_new_anchor():
    gate = PoseFence("robot-01")
    gate.observe(pose(), 100)
    gate.observe(pose(seq=2, sample_us=1_100_000), 100.1)
    assert gate.current(100.1) is not None
    gate.invalidate("http_unavailable")
    assert gate.current(100.1) is None
    with pytest.raises(PoseError, match="re-anchor"):
        gate.observe(pose(body_boot=10, origin=1, seq=1, sample_us=500), 100.2)
    gate.observe(pose(body_boot=10, origin=1, seq=2, sample_us=100_500), 100.3)
    assert gate.current(100.31) is None
    gate.observe(pose(body_boot=10, origin=1, seq=3, sample_us=200_500), 100.4)
    assert gate.current(100.41) is not None
    assert gate.needs_reanchor
    with pytest.raises(PoseError, match="Retired"):
        gate.observe(pose(seq=4, sample_us=1_200_000), 100.5)


def test_same_body_origin_new_head_boot_is_a_hard_discontinuity():
    gate = PoseFence("robot-01")
    gate.observe(pose(), 1)
    with pytest.raises(PoseError, match="head boot changed"):
        gate.observe(pose(head_boot=13, seq=2, sample_us=1_100_000), 1.1)
    assert gate.needs_reanchor


def test_source_older_than_new_receipt_is_rejected_without_new_origin():
    gate = PoseFence("robot-01")
    gate.observe(pose(), 100)
    with pytest.raises(PoseError, match="lags"):
        gate.observe(pose(seq=2, sample_us=1_010_000), 101)
    assert gate.current(101) is None
    assert gate.blocked_reason == "stale_body_sample"


def test_receipt_expiry_refuses_cached_pose():
    gate = PoseFence("robot-01")
    gate.observe(pose(), 5)
    gate.observe(pose(seq=2, sample_us=1_100_000), 5.1)
    assert gate.current(5.5) is None
    assert gate.needs_reanchor
    assert gate.blocked_reason == "stale_receipt"


def test_degraded_and_unavailable_do_not_admit_planning():
    for quality in ("degraded", "unavailable"):
        gate = PoseFence("robot-01")
        gate.observe(pose(quality=quality), 100)
        gate.observe(pose(seq=2, sample_us=1_100_000, quality="valid"), 100.1)
        assert gate.current(100.1) is None
        gate.observe(pose(seq=3, sample_us=1_200_000), 100.2)
        assert gate.current(100.2) is not None


def test_body_clock_implausible_forward_jump_latches():
    gate = PoseFence("robot-01")
    gate.observe(pose(), 100)
    with pytest.raises(PoseError, match="implausibly"):
        gate.observe(pose(seq=2, sample_us=20_000_000), 100.1)
    assert gate.current(100.1) is None


def test_failed_http_read_needs_two_new_samples_before_local_freshness():
    gate = PoseFence("robot-01")
    gate.observe(pose(), 10.0)
    gate.observe(pose(seq=2, sample_us=1_100_000), 10.1)
    assert gate.current(10.1) is not None
    gate.invalidate("missing_pose")
    gate.observe(pose(seq=3, sample_us=1_200_000), 10.2)
    assert gate.current(10.2) is None
    gate.observe(pose(seq=4, sample_us=1_300_000), 10.3)
    assert gate.current(10.3) is not None
    assert gate.needs_reanchor
