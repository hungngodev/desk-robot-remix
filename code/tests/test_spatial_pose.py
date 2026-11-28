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
    {"sample_us": (1 << 53)}, {"body_boot": -1}, {"body_boot": 0},
    {"origin": -1}, {"origin": 0}, {"origin": 0, "quality": "degraded"},
    {"head_boot": -1}, {"quality": "excellent"},
    {"yaw_mrad": 3143}, {"x_mm": 1_000_001}, {"y_mm": -1_000_001},
    {"x_mm": 1.0}, {"head_boot": False},
])
def test_bad_pose_fields_fail_closed(updates):
    with pytest.raises(PoseError):
        decode_pose(pose(**updates), "robot-01", 100.0)


@pytest.mark.parametrize("updates", [
    {"unexpected": 1}, {"seq\x00": 2}, {"quality\x00": "valid"},
    {"unexpected": float("nan")},
])
def test_unknown_v1_fields_invalidate_current_pose(updates):
    with pytest.raises(PoseError, match="Unexpected pose field"):
        decode_pose(pose(**updates), "robot-01", 100.0)

    gate = PoseFence("robot-01")
    gate.observe(pose(), 100.0)
    accepted = gate.observe(pose(seq=2, sample_us=1_100_000), 100.1)
    assert gate.current(100.1) is accepted

    with pytest.raises(PoseError, match="Unexpected pose field"):
        gate.observe(pose(seq=3, sample_us=1_200_000, **updates), 100.2)
    assert gate.current(100.2) is None
    assert gate.needs_reanchor
    assert gate.blocked_reason == "invalid_pose"
    assert not gate.owns_continuous_receipt(accepted)


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


def test_exact_json_sample_bound_and_zero_origin_unavailable_diagnostic():
    maximum = decode_pose(pose(sample_us=(1 << 53) - 1), "robot-01", 42.0)
    assert maximum.sample_us == (1 << 53) - 1
    unlocalized = pose(origin=0, quality="unavailable")
    decoded = decode_pose(unlocalized, "robot-01", 42.0)
    assert decoded.origin == 0 and decoded.quality == "unavailable"
    gate = PoseFence("robot-01")
    gate.observe(unlocalized, 100.0)
    gate.observe(pose(origin=0, quality="unavailable", seq=2,
                      sample_us=1_100_000), 100.1)
    assert gate.current(100.1) is None
    assert gate.needs_reanchor


def test_legacy_head_pose_is_diagnostic_only():
    gate = PoseFence("robot-01")
    gate.observe(pose(head_boot=None), 100.0)
    packet = pose(seq=2, sample_us=1_100_000)
    del packet["head_boot"]
    receipt = gate.observe(packet, 100.1)
    assert receipt.head_boot is None
    assert gate.current(100.1) is None
    assert gate.needs_reanchor
    assert gate.blocked_reason == "missing_head_boot"
    with pytest.raises(PoseError, match="Pose sequence"):
        gate.observe(packet, 100.2)


def test_missing_head_identity_invalidates_without_retiring_known_boot():
    gate = PoseFence("robot-01")
    gate.observe(pose(), 100.0)
    gate.observe(pose(seq=2, sample_us=1_100_000), 100.1)
    assert gate.current(100.1) is not None
    with pytest.raises(PoseError, match="head boot identity"):
        gate.observe(pose(head_boot=None, seq=3, sample_us=1_200_000), 100.2)
    assert gate.current(100.2) is None
    assert gate.blocked_reason == "missing_head_boot"
    gate.observe(pose(seq=4, sample_us=1_300_000), 100.3)
    assert gate.current(100.3) is None
    fresh = gate.observe(pose(seq=5, sample_us=1_400_000), 100.4)
    assert gate.current(100.4) == fresh
    assert gate.needs_reanchor


def test_identified_head_after_legacy_requires_new_baseline():
    gate = PoseFence("robot-01")
    gate.observe(pose(head_boot=None), 100.0)
    with pytest.raises(PoseError, match="re-anchor"):
        gate.observe(pose(seq=2, sample_us=1_100_000), 100.1)
    gate.observe(pose(seq=3, sample_us=1_200_000), 100.2)
    assert gate.current(100.2) is None
    fresh = gate.observe(pose(seq=4, sample_us=1_300_000), 100.3)
    assert gate.current(100.3) == fresh


def test_http_request_age_is_not_renewed_by_receipt():
    gate = PoseFence("robot-01")
    gate.observe(pose(), 100.0, request_started_at=99.95)
    fresh = gate.observe(pose(seq=2, sample_us=1_200_000), 100.2,
                         request_started_at=100.0)
    assert fresh.received_at == 100.2
    assert fresh.request_started_at == 100.0
    assert gate.current(100.24) == fresh
    assert gate.current(100.26) is None
    assert gate.needs_reanchor


def test_slow_http_pose_cannot_supply_a_new_baseline():
    gate = PoseFence("robot-01")
    for seq in (1, 2):
        start = 100.0 + (seq - 1) * 0.6
        with pytest.raises(PoseError, match="request age"):
            gate.observe(pose(seq=seq, sample_us=seq * 600_000), start + 0.6,
                         request_started_at=start)
        assert gate.current(start + 0.6) is None
        assert gate.blocked_reason == "pose_transport_delayed"
    gate.observe(pose(seq=3, sample_us=1_800_000), 101.21,
                 request_started_at=101.20)
    assert gate.current(101.21) is None
    fresh = gate.observe(pose(seq=4, sample_us=1_900_000), 101.31,
                         request_started_at=101.30)
    assert gate.current(101.31) == fresh


@pytest.mark.parametrize("now, max_age_s", [
    (float("nan"), 0.25), (float("inf"), 0.25), (True, 0.25),
    (100.1, float("nan")), (100.1, 0), (100.1, 2), (100.1, True),
])
def test_invalid_freshness_read_revokes_cached_continuity(now, max_age_s):
    gate = PoseFence("robot-01")
    gate.observe(pose(), 100.0)
    gate.observe(pose(seq=2, sample_us=1_100_000), 100.1)
    assert gate.current(100.1) is not None

    assert gate.current(now, max_age_s=max_age_s) is None
    assert gate.blocked_reason == "invalid_freshness_window"
    assert gate.needs_reanchor
    assert gate.current(100.1) is None

    gate.observe(pose(seq=3, sample_us=1_200_000), 100.2)
    assert gate.current(100.2) is None
    fresh = gate.observe(pose(seq=4, sample_us=1_300_000), 100.3)
    assert gate.current(100.3) == fresh
    assert gate.needs_reanchor


def test_progressive_body_clock_lag_cannot_renew_current_pose():
    gate = PoseFence("robot-01")
    for i in range(2):
        now = 100.0 + i * 0.30
        gate.observe(pose(seq=i + 1, sample_us=1_000_000 + i * 100_000),
                     now, request_started_at=now - 0.01)
    assert gate.current(100.30) is not None
    for i in range(2, 7):
        now = 100.0 + i * 0.30
        with pytest.raises(PoseError, match="lags"):
            gate.observe(pose(seq=i + 1, sample_us=1_000_000 + i * 100_000),
                         now, request_started_at=now - 0.01)
        assert gate.current(now) is None
        assert gate.needs_reanchor
    # A transport failure must not erase the relative clock baseline.
    gate.invalidate("http_unavailable")
    with pytest.raises(PoseError, match="lags"):
        gate.observe(pose(seq=8, sample_us=1_700_000), 102.1,
                     request_started_at=102.09)
    # Source catch-up restores only local continuity, never map localization.
    gate.observe(pose(seq=9, sample_us=3_200_000), 102.2,
                 request_started_at=102.19)
    assert gate.current(102.2) is None
    fresh = gate.observe(pose(seq=10, sample_us=3_300_000), 102.3,
                         request_started_at=102.29)
    assert gate.current(102.3) is fresh
    assert gate.needs_reanchor


def test_matching_rate_pose_remains_current_across_many_receipts():
    gate = PoseFence("robot-01")
    for i in range(100):
        now = 100.0 + i * 0.30
        reading = gate.observe(pose(seq=i + 1, sample_us=1_000_000 + i * 300_000),
                               now, request_started_at=now - 0.01)
        assert gate.current(now) is (reading if i else None)


def test_relative_lag_consumes_current_pose_freshness_budget():
    gate = PoseFence("robot-01")
    gate.observe(pose(), 100.0, request_started_at=99.99)
    fresh = gate.observe(pose(seq=2, sample_us=1_100_000), 100.3,
                         request_started_at=100.29)
    assert gate.current(100.32) is fresh
    assert gate.current(100.36) is None
    assert gate.needs_reanchor


def test_relative_clock_baseline_resets_only_for_new_identity():
    gate = PoseFence("robot-01")
    gate.observe(pose(), 100.0)
    gate.observe(pose(seq=2, sample_us=1_100_000), 100.3)
    with pytest.raises(PoseError, match="lags"):
        gate.observe(pose(seq=3, sample_us=1_200_000), 100.6)
    with pytest.raises(PoseError, match="re-anchor"):
        gate.observe(pose(body_boot=10, origin=1, sample_us=10), 101.0)
    gate.observe(pose(body_boot=10, origin=1, seq=2, sample_us=100_010), 101.1)
    assert gate.current(101.1) is None
    fresh = gate.observe(pose(body_boot=10, origin=1, seq=3, sample_us=200_010), 101.2)
    assert gate.current(101.2) is fresh
    assert gate.needs_reanchor


@pytest.mark.parametrize("bad", [10**400, -(10**400), 1e300, -1e300],
                         ids=["huge-int", "negative-int", "huge-float", "negative-float"])
def test_excessive_pose_clock_values_revoke_continuity(bad):
    with pytest.raises(PoseError):
        decode_pose(pose(), "robot-01", bad)
    for boundary in ("receipt", "request", "now", "window"):
        gate = PoseFence("robot-01")
        gate.observe(pose(), 100.0)
        fresh = gate.observe(pose(seq=2, sample_us=1_100_000), 100.1)
        assert gate.current(100.1) is fresh
        packet = pose(seq=3, sample_us=1_200_000)
        if boundary == "receipt":
            with pytest.raises(PoseError):
                gate.observe(packet, bad)
        elif boundary == "request":
            with pytest.raises(PoseError):
                gate.observe(packet, 100.2, request_started_at=bad)
        elif boundary == "now":
            assert gate.current(bad) is None
        else:
            assert gate.current(100.2, max_age_s=bad) is None
        assert gate.current(100.2) is None
        assert not gate.owns_continuous_receipt(fresh)
        assert gate.needs_reanchor
        gate.observe(packet, 100.2)
        assert gate.current(100.2) is None
        recovered = gate.observe(pose(seq=4, sample_us=1_300_000), 100.3)
        assert gate.current(100.3) is recovered


@pytest.mark.parametrize("field", ["x_mm", "y_mm", "yaw_mrad", "seq", "sample_us"])
@pytest.mark.parametrize("bad_value", [
    True,
    False,
    None,
    float("nan"),
    float("inf"),
    float("-inf"),
    "__MISSING__",
], ids=["true", "false", "none", "nan", "inf", "neg_inf", "missing"])
def test_malformed_or_missing_coordinate_clears_pose_and_requires_reanchor(
    field, bad_value,
):
    gate = PoseFence("robot-01")
    gate.observe(pose(), 100.0)
    fresh = gate.observe(pose(seq=2, sample_us=1_100_000), 100.1)
    assert gate.current(100.1) is fresh

    corrupted = pose(seq=3, sample_us=1_200_000)
    if bad_value == "__MISSING__":
        del corrupted[field]
    else:
        corrupted[field] = bad_value

    with pytest.raises(PoseError):
        decode_pose(corrupted, "robot-01", 100.2)
    with pytest.raises(PoseError):
        gate.observe(corrupted, 100.2)
    assert gate.current(100.2) is None
    assert not gate.owns_continuous_receipt(fresh)
    assert gate.needs_reanchor is True
