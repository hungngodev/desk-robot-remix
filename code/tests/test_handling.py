"""Source-grounded MPU6050 handling behavior, not physical calibration proof."""
import math
from itertools import permutations, product

import pytest
from desk_robot import handling
from desk_robot.handling import HandlingGate, mpu6050_temperature_raw, raw_mpu6050


def sample(
    acc=(0, 0, 16384), gyro=(0, 0, 0), *,
    family=4, valid=True, age=20, left=0, right=0, drive_ms=0,
    boot_id=1, sample_ms=1,
):
    return {
        "left": left, "right": right, "drive_ms": drive_ms,
        "imu": {
            "family": family, "gyro_id": 0x68,
            "aux_id": 0, "valid": valid,
            "acc": list(acc), "gyro": list(gyro), "age_ms": age,
            "boot_id": boot_id, "sample_ms": sample_ms,
        }
    }


def canonical_wroom_sample(**kwargs):
    """Use the same nested motor keys as BodyControl::status JSON."""
    frame = sample(**kwargs)
    frame["motor"] = {"m0": frame.pop("left"), "m1": frame.pop("right")}
    return frame


def test_real_wroom_nested_motor_schema_recovers_handling_events():
    frame = canonical_wroom_sample()
    result = raw_mpu6050(frame)
    assert result is not None and result[0] == (0, 0, 1)
    gate = HandlingGate()
    for i in range(8):
        assert qualified(gate, canonical_wroom_sample(), 100 + i * .15) == ()
    assert gate.reference == (0, 0, 1)
    tilted = canonical_wroom_sample(acc=(12551, 0, 10531))
    assert qualified(gate, tilted, 102.0) == ()
    assert qualified(gate, tilted, 102.2) == ("handling_tilt",)


def test_real_wroom_motion_and_conflicting_legacy_fields_fail_closed():
    for frame in (
        canonical_wroom_sample(left=25),
        canonical_wroom_sample(right=-30),
        canonical_wroom_sample(drive_ms=250),
        dict(canonical_wroom_sample(), left=0, right=0,
             motor={"m0": 20, "m1": 0}),
        dict(canonical_wroom_sample(), motor={"m0": True, "m1": 0}),
        dict(canonical_wroom_sample(), motor={"m0": "0", "m1": 0}),
        dict(canonical_wroom_sample(), motor={"m0": 0}),
    ):
        assert raw_mpu6050(frame) is None
    gate = HandlingGate()
    for i in range(8):
        qualified(gate, canonical_wroom_sample(), 100 + i * .15)
    assert gate.reference is not None
    # Even a late callback from the motor-active envelope revokes pose.
    assert qualified(gate, canonical_wroom_sample(left=30), 100.1) == ()
    assert gate.reference is None


def qualified(gate, body, now, *, new_sample=True):
    if new_sample:
        body["imu"]["sample_ms"] = int(round(now * 1000)) & 0xffffffff
    return gate.observe(
        body, now, qualified=True, calibrated=True,
        tilt_threshold_deg=38, shake_delta_mg=550,
    )


def calibrated(gate, start=100.0):
    for index in range(8):
        assert qualified(gate, sample(), start + .15 * index) == ()
    assert gate.reference is not None


def test_real_mpu_scaled_only_if_wroom_source_fresh_stationary_and_valid():
    a, dps = raw_mpu6050(sample(acc=(0, 0, 16384), gyro=(0, 131, 0)))
    assert a == (0, 0, 1)
    assert dps == 1
    for body in (
        sample(family=3), sample(age=201), sample(valid=False),
        sample(left=1), sample(right=1), sample(drive_ms=250),
        sample(acc=(True, 0, 100)), sample(gyro=(0, 0)),
        sample(acc=(40000, 0, 0)),
    ):
        assert raw_mpu6050(body) is None


def test_mpu_identity_mismatch_cannot_seed_handling_calibration():
    gate = HandlingGate()
    for wrong in (None, True, 0, 0x69, "104"):
        frame = sample()
        frame["imu"]["gyro_id"] = wrong
        assert raw_mpu6050(frame) is None
        assert gate.observe(frame, 100.0, qualified=True, calibrated=True) == ()
        assert gate.reference is None and gate.startup_samples == []
    # A correctly identified, fresh acquisition can begin qualification.
    assert qualified(gate, sample(sample_ms=2), 100.2, new_sample=False) == ()
    assert len(gate.startup_samples) == 1


def test_imu_disabled_by_default_never_creates_unqualified_event():
    gate = HandlingGate()
    for i in range(15):
        assert gate.observe(sample(acc=(16000, 0, 0)), 100 + i * .15,
                            qualified=False) == ()
    assert gate.reference is None


@pytest.mark.parametrize("kwargs", [{}, {"calibrated": False}])
def test_provisional_thresholds_never_seed_pose_or_emit_events(kwargs):
    gate = HandlingGate()
    for i in range(8):
        assert gate.observe(
            sample(sample_ms=1000 + i), 100 + i * .15, qualified=True, **kwargs,
        ) == ()
    for i in range(2):
        assert gate.observe(
            sample(acc=(12551, 0, 10531), sample_ms=1010 + i),
            102 + i * .15, qualified=True, **kwargs,
        ) == ()
    assert gate.reference is None
    assert gate.startup_samples == []


def test_calibration_attestation_revocation_preserves_acquisition_fence():
    gate = HandlingGate()
    calibrated(gate)
    previous = (gate.last_boot_id, gate.last_sample_ms, gate.last_shake)
    assert gate.observe(sample(), 102.0, qualified=True, calibrated=False) == ()
    assert gate.reference is None
    assert gate.gyro_bias_dps is None
    assert (gate.last_boot_id, gate.last_sample_ms, gate.last_shake) == previous


@pytest.mark.parametrize("value", [1, "true", None])
def test_calibration_attestation_requires_real_boolean(value):
    with pytest.raises(ValueError, match="Physically qualified"):
        HandlingGate().observe(sample(), 100.0, qualified=True, calibrated=value)


def test_imu_requires_eight_still_upright_baseline_reads():
    gate = HandlingGate()
    for i in range(7):
        assert qualified(gate, sample(), 100 + .15 * i) == ()
    assert gate.reference is None
    assert qualified(gate, sample(gyro=(2000, 0, 0)), 101.10) == ()
    assert gate.startup_samples == []  # rotating robot cannot set a baseline
    calibrated(gate, 102)
    assert gate.reference == (0, 0, 1)


def test_stationary_gyro_bias_is_estimated_and_used_for_qualified_tilt():
    """A stable 3 dps offset is not 3 dps of deliberate human rotation."""
    gate = HandlingGate()
    for i in range(8):
        assert qualified(
            gate, sample(gyro=(393, -262, 131)),
            100.0 + 0.15 * i,
        ) == ()
    assert gate.reference == (0, 0, 1)
    assert gate.gyro_bias_dps == pytest.approx((3.0, -2.0, 1.0))
    assert gate.startup_gyro_samples == []
    tilt = sample(acc=(12551, 0, 10531), gyro=(393, -262, 131))
    assert qualified(gate, tilt, 102.0) == ()
    assert qualified(gate, tilt, 102.2) == ("handling_tilt",)
    # Revoking physical qualification invalidates the bias as well as pose.
    assert gate.observe(sample(), 102.4, qualified=False) == ()
    assert gate.reference is None
    assert gate.gyro_bias_dps is None


def test_gyro_bias_calibration_rejects_inconsistent_stationary_claims():
    gate = HandlingGate()
    for i in range(7):
        assert qualified(gate, sample(), 100.0 + 0.15 * i) == ()
    # A last sample at 6 dps still passes the instantaneous 7 dps guard,
    # but the window is not steady enough to estimate a trustworthy bias.
    assert qualified(gate, sample(gyro=(786, 0, 0)), 101.15) == ()
    assert gate.reference is None
    assert gate.gyro_bias_dps is None
    assert gate.startup_gyro_samples == []
    calibrated(gate, 102)
    assert gate.reference == (0, 0, 1)
    assert gate.gyro_bias_dps == pytest.approx((0, 0, 0))


def test_mpu_tilt_is_relative_to_actual_stationary_mount_not_body_axis():
    gate = HandlingGate()
    calibrated(gate)
    # A stationary 50-degree tilt relative to baseline, approximate 1g.
    tilted = sample(acc=(12551, 0, 10531))
    assert qualified(gate, tilted, 102.0) == ()
    assert qualified(gate, tilted, 102.2) == ("handling_tilt",)
    assert qualified(gate, tilted, 102.4) == ()
    # Return to upright for hysteresis and report a later distinct tilt.
    assert qualified(gate, sample(), 102.6) == ()
    assert qualified(gate, tilted, 102.8) == ()
    assert qualified(gate, tilted, 103.0) == ("handling_tilt",)


def test_mpu_shake_needs_synchronized_accel_and_rotation_with_cooldown():
    gate = HandlingGate()
    calibrated(gate)
    shaking = sample(acc=(0, 0, 26000), gyro=(16500, 0, 0))
    assert qualified(gate, shaking, 102.0) == ()
    assert qualified(gate, shaking, 102.15) == ("handling_shake",)
    assert qualified(gate, shaking, 102.30) == ()
    assert qualified(gate, shaking, 102.45) == ()
    assert qualified(gate, sample(), 102.60) == ()
    # Maintain the same live observation stream instead of accidentally
    # exercising a disconnected/reconnected IMU generation.
    for when in (103.1, 103.6, 104.1, 104.6, 105.1):
        assert qualified(gate, sample(), when) == ()
    assert qualified(gate, shaking, 105.20) == ()
    assert qualified(gate, shaking, 105.40) == ("handling_shake",)


def test_imu_motion_during_drive_cannot_trigger_handling_or_retain_calibration():
    gate = HandlingGate()
    calibrated(gate)
    assert qualified(gate, sample(acc=(13000, 0, 9000), left=40), 102.0) == ()
    assert gate.reference is None
    assert qualified(gate, sample(acc=(13000, 0, 9000)), 102.15) == ()
    assert gate.reference is None


def test_stale_generation_freshness_reset_and_no_unsupported_berryimu_scale():
    gate = HandlingGate()
    calibrated(gate)
    assert qualified(gate, sample(family=2), 102.0) == ()
    assert gate.reference is None
    calibrated(gate, 103)
    assert qualified(gate, sample(age=500), 105) == ()
    assert gate.reference is None
    calibrated(gate, 106)
    assert qualified(gate, sample(), 111) == ()
    assert gate.reference is None  # long gap resets before new source


@pytest.mark.parametrize("bad", [
    (False, 24, 550), (True, 0, 550), (True, 39, 1900),
])
def test_invalid_qualification_parameters_refuse_events(bad):
    # Each caller must supply a coherent boolean and bounded measured knobs.
    gate = HandlingGate()
    qualified, angle, delta = bad
    with pytest.raises(ValueError):
        gate.observe(sample(), 1, qualified=qualified,
                     tilt_threshold_deg=angle, shake_delta_mg=delta)


def test_same_acquisition_never_counts_twice_for_calibration_or_tilt():
    gate = HandlingGate()
    frame = sample(sample_ms=10)
    for i in range(8):
        assert qualified(gate, frame, 100 + i * .1, new_sample=False) == ()
    assert gate.reference is None
    assert len(gate.startup_samples) == 1

    for i in range(7):
        assert qualified(gate, sample(sample_ms=11 + i), 100.8 + i * .1,
                         new_sample=False) == ()
    assert gate.reference == (0, 0, 1)
    tilt = sample(acc=(12551, 0, 10531), sample_ms=18)
    assert qualified(gate, tilt, 101.5, new_sample=False) == ()
    assert qualified(gate, tilt, 101.6, new_sample=False) == ()
    assert gate.tilt_hits == 1
    assert qualified(gate, sample(acc=(12551, 0, 10531), sample_ms=19),
                     101.7, new_sample=False) == ("handling_tilt",)


def test_boot_change_and_fake_clock_wrap_cannot_erase_new_baseline():
    gate = HandlingGate()
    calibrated(gate)
    assert qualified(gate, sample(boot_id=2, sample_ms=5),
                     102.0, new_sample=False) == ()
    assert gate.reference is None
    assert len(gate.startup_samples) == 1
    # Reestablish only from independent source conversions.
    for i in range(7):
        assert qualified(gate, sample(boot_id=2, sample_ms=6 + i),
                         102.15 + .15 * i, new_sample=False) == ()
    assert gate.reference == (0, 0, 1)
    # A huge forward clock jump is not a believable immediate rollover.
    # Keep the real new-boot baseline and reject both this implausible
    # packet and the ensuing old acquisition, instead of resetting pose.
    assert qualified(gate, sample(boot_id=2, sample_ms=0xfffffffe),
                     103.4, new_sample=False) == ()
    assert gate.reference == (0, 0, 1)
    assert qualified(gate, sample(boot_id=2, sample_ms=2),
                     103.55, new_sample=False) == ()
    assert gate.reference == (0, 0, 1)
    assert gate.last_sample_ms == 12


def test_missing_or_malformed_imu_source_identity_fails_quiet():
    for identity in (
        {"boot_id": 0}, {"boot_id": True}, {"sample_ms": -1},
        {"sample_ms": 0x100000000}, {"sample_ms": "12"},
    ):
        frame = sample()
        frame["imu"].update(identity)
        assert raw_mpu6050(frame) is None
    for missing in ("boot_id", "sample_ms"):
        frame = sample()
        del frame["imu"][missing]
        assert raw_mpu6050(frame) is None


@pytest.mark.parametrize("field,value", [
    ("now", None), ("now", "100"), ("now", True),
    ("now", float("nan")), ("now", float("inf")),
    ("now", 10 ** 1000), ("now", -(10 ** 1000)),
    ("tilt_threshold_deg", 10 ** 1000),
    ("tilt_threshold_deg", None), ("tilt_threshold_deg", "38"),
    ("tilt_threshold_deg", True), ("tilt_threshold_deg", float("nan")),
])
def test_malformed_handling_parameters_raise_value_error_without_state_change(field, value):
    gate = HandlingGate()
    arguments = {"now": 100.0, "qualified": True, "tilt_threshold_deg": 38.0}
    arguments[field] = value
    with pytest.raises(ValueError, match="Physically qualified"):
        gate.observe(sample(), **arguments)
    assert gate.reference is None
    assert gate.startup_samples == []


def test_repeated_shake_sample_does_not_reconfirm_gesture():
    gate = HandlingGate()
    calibrated(gate)
    shake = sample(acc=(0, 0, 26000), gyro=(16500, 0, 0),
                   sample_ms=200000)
    assert qualified(gate, shake, 102.0, new_sample=False) == ()
    for i in range(6):
        assert qualified(gate, shake, 102.05 + .05 * i,
                         new_sample=False) == ()
    assert gate.shake_hits == 1
    assert qualified(gate, sample(acc=(0, 0, 26000), gyro=(16500, 0, 0),
                                  sample_ms=200001),
                     102.5, new_sample=False) == ("handling_shake",)


def test_reconnect_cannot_reuse_same_imu_conversion_as_new_baseline():
    gate = HandlingGate()
    frame = sample(sample_ms=9000)
    assert qualified(gate, frame, 100.0, new_sample=False) == ()
    assert len(gate.startup_samples) == 1
    # A reconnect with falsely refreshed age_ms is not a new conversion.
    assert qualified(gate, frame, 102.0, new_sample=False) == ()
    assert gate.reference is None and gate.startup_samples == []
    assert qualified(gate, frame, 102.1, new_sample=False) == ()
    assert gate.startup_samples == []
    # A genuinely new conversion may start a new stationary calibration.
    assert qualified(gate, sample(sample_ms=9001), 102.2, new_sample=False) == ()
    assert len(gate.startup_samples) == 1


def test_malformed_status_cannot_erase_last_imu_conversion_identity():
    gate = HandlingGate()
    first = sample(sample_ms=9000)
    assert qualified(gate, first, 100.0, new_sample=False) == ()
    assert len(gate.startup_samples) == 1
    # A dropped status must clear pose calibration, but not allow a replay.
    assert qualified(gate, sample(sample_ms=9000, age=201),
                     100.1, new_sample=False) == ()
    assert gate.reference is None and gate.startup_samples == []
    assert qualified(gate, first, 100.2, new_sample=False) == ()
    assert gate.startup_samples == []
    assert qualified(gate, sample(sample_ms=9001),
                     100.3, new_sample=False) == ()
    assert len(gate.startup_samples) == 1
    # A stopped motor report must not erase the same source replay fence.
    assert qualified(gate, sample(sample_ms=9001, left=1),
                     100.4, new_sample=False) == ()
    assert qualified(gate, sample(sample_ms=9001),
                     100.5, new_sample=False) == ()
    assert gate.startup_samples == []
    assert qualified(gate, sample(sample_ms=9002),
                     100.6, new_sample=False) == ()
    assert len(gate.startup_samples) == 1


def test_implausible_acceleration_preserves_last_conversion_replay_fence():
    gate = HandlingGate()
    assert qualified(gate, sample(sample_ms=500), 100.0, new_sample=False) == ()
    assert len(gate.startup_samples) == 1
    # Valid signed raw readings but physically implausible near-zero gravity.
    bad = sample(acc=(0, 0, 0), sample_ms=501)
    assert qualified(gate, bad, 100.1, new_sample=False) == ()
    assert gate.reference is None and gate.startup_samples == []
    assert gate.last_boot_id == 1 and gate.last_sample_ms == 501
    # The same conversion must not be reused with a corrected payload.
    assert qualified(gate, sample(sample_ms=501), 100.2, new_sample=False) == ()
    assert gate.startup_samples == []
    assert qualified(gate, sample(sample_ms=502), 100.3, new_sample=False) == ()
    assert len(gate.startup_samples) == 1


def test_same_boot_timestamp_regression_cannot_reseed_calibration():
    gate = HandlingGate()
    for i in range(8):
        assert qualified(gate, sample(sample_ms=1000 + i),
                         100.0 + i * .1, new_sample=False) == ()
    assert gate.reference is not None
    # A delayed old packet has the same boot identity but a lower timestamp.
    assert qualified(gate, sample(sample_ms=1002), 100.9,
                     new_sample=False) == ()
    assert gate.reference is not None
    assert gate.last_sample_ms == 1007
    last_at = gate.last_at
    for i in range(8):
        assert qualified(gate, sample(sample_ms=1002),
                         101.0 + i * .1, new_sample=False) == ()
    assert gate.reference is not None
    assert gate.last_at == last_at
    assert gate.startup_samples == []
    # A genuine forward polling gap still invalidates the pose.
    assert qualified(gate, sample(sample_ms=1008), 101.9,
                     new_sample=False) == ()
    assert gate.reference is None


def test_near_uint32_wrap_still_requires_new_stationary_baseline():
    gate = HandlingGate()
    assert qualified(gate, sample(sample_ms=0xfffffffe), 100.0,
                     new_sample=False) == ()
    assert qualified(gate, sample(sample_ms=2), 100.1,
                     new_sample=False) == ()
    assert gate.last_sample_ms == 2
    assert len(gate.startup_samples) == 1


def test_inconsistent_startup_vectors_do_not_reuse_last_conversion():
    """Opposing individually plausible 1g readings cannot erase replay identity."""
    gate = HandlingGate()
    for i in range(8):
        vector = (0, 0, 16384 if i < 4 else -16384)
        assert qualified(gate, sample(acc=vector, sample_ms=200 + i),
                         100 + i * .1, new_sample=False) == ()
    assert gate.reference is None
    assert gate.last_sample_ms == 207
    assert gate.startup_samples == []

    # Repeated final conversion cannot count toward the next baseline.
    for i in range(8):
        assert qualified(gate, sample(sample_ms=207),
                         101 + i * .1, new_sample=False) == ()
    assert gate.startup_samples == []
    for i in range(8):
        assert qualified(gate, sample(sample_ms=208 + i),
                         102 + i * .1, new_sample=False) == ()
    assert gate.reference == (0, 0, 1)


def test_delayed_old_boot_cannot_displace_new_boot_calibration():
    gate = HandlingGate()
    for i in range(8):
        assert qualified(gate, sample(boot_id=11, sample_ms=100 + i),
                         100 + i * .1, new_sample=False) == ()
    assert gate.reference is not None
    assert qualified(gate, sample(boot_id=22, sample_ms=1),
                     101, new_sample=False) == ()
    assert gate.reference is None
    assert gate.last_boot_id == 22
    for i in range(2, 9):
        assert qualified(gate, sample(boot_id=22, sample_ms=i),
                         101 + i * .1, new_sample=False) == ()
    assert gate.reference is not None
    # A delayed old boot packet cannot force another reset or become current.
    assert qualified(gate, sample(boot_id=11, sample_ms=500),
                     102, new_sample=False) == ()
    assert gate.last_boot_id == 22
    assert gate.reference is not None
    assert qualified(gate, sample(boot_id=22, sample_ms=9),
                     102.1, new_sample=False) == ()


def test_qualification_reenable_rejects_replayed_conversion():
    gate = HandlingGate()
    frame = sample(sample_ms=4000)
    assert qualified(gate, frame, 100.0, new_sample=False) == ()
    assert len(gate.startup_samples) == 1
    # Physical qualification may be revoked without a WROOM reboot.
    assert gate.observe(frame, 100.1, qualified=False) == ()
    assert gate.reference is None and gate.startup_samples == []
    assert gate.last_boot_id == 1 and gate.last_sample_ms == 4000
    for i in range(8):
        assert qualified(gate, frame, 100.2 + i * .1, new_sample=False) == ()
    assert gate.startup_samples == []
    assert qualified(gate, sample(sample_ms=4001), 101.1,
                     new_sample=False) == ()
    assert len(gate.startup_samples) == 1


def test_malformed_retired_boot_packet_cannot_erase_new_boot_calibration():
    gate = HandlingGate()
    calibrated(gate, 100)
    assert qualified(gate, sample(boot_id=2), 102) == ()
    # A new WROOM boot can only calibrate from its OWN seven additional
    # physical acquisitions. The original helper defaults to retired boot 1
    # and must never be allowed to restore boot 2's pose.
    for i in range(7):
        assert qualified(gate, sample(boot_id=2), 102.15 + .15 * i) == ()
    assert gate.reference is not None
    assert gate.last_boot_id == 2
    assert gate.reference is not None
    # A delayed packet from boot 1 must not revoke the valid boot 2 pose.
    assert qualified(gate, sample(boot_id=1, valid=False), 105) == ()
    assert gate.last_boot_id == 2
    assert gate.reference is not None
    # A malformed packet from the CURRENT boot must still fail closed.
    assert qualified(gate, sample(boot_id=2, valid=False), 105.1) == ()
    assert gate.reference is None


def test_pre_wrap_delayed_packet_cannot_reseed_after_clock_wrap():
    gate = HandlingGate()
    assert qualified(gate, sample(sample_ms=0xfffffffe), 100,
                     new_sample=False) == ()
    assert qualified(gate, sample(sample_ms=2), 100.1,
                     new_sample=False) == ()
    assert gate.last_sample_ms == 2
    assert len(gate.startup_samples) == 1
    # This is older in acquisition order but numerically larger.
    for i in range(8):
        assert qualified(gate, sample(sample_ms=0xffffffff),
                         100.2 + i * .1, new_sample=False) == ()
    assert gate.last_sample_ms == 2
    assert len(gate.startup_samples) == 1
    assert qualified(gate, sample(sample_ms=3), 101.1,
                     new_sample=False) == ()
    assert gate.last_sample_ms == 3
    assert len(gate.startup_samples) == 2


def test_late_retired_boot_delivery_does_not_reset_current_calibration():
    gate = HandlingGate()
    calibrated(gate, 100)
    # Establish a new boot and qualify its own eight distinct conversions.
    assert qualified(gate, sample(boot_id=2), 102) == ()
    for i in range(7):
        assert qualified(gate, sample(boot_id=2), 102.15 + i * .15) == ()
    assert gate.reference is not None
    previous_at = gate.last_at
    previous_sample = gate.last_sample_ms

    # Even a malformed old packet arriving after a host poll gap cannot
    # invalidate the active boot's pose or advance its acquisition clock.
    assert qualified(gate, sample(boot_id=1, valid=False),
                     previous_at + 1.5, new_sample=False) == ()
    assert gate.reference is not None
    assert gate.last_at == previous_at
    assert gate.last_sample_ms == previous_sample

    # The same gap on a CURRENT boot must still invalidate calibration.
    assert qualified(gate, sample(boot_id=2, sample_ms=previous_sample + 1),
                     previous_at + 1.6, new_sample=False) == ()
    assert gate.reference is None


def test_retired_boot_history_exhaustion_fails_closed_without_replay_eviction():
    gate = HandlingGate()
    # Eight legitimate boot transitions fill the bounded replay history.
    for boot in range(1, 10):
        assert qualified(gate, sample(boot_id=boot, sample_ms=boot),
                         100 + boot * .1, new_sample=False) == ()
    assert gate.last_boot_id == 9
    assert gate.retired_boot_ids == list(range(1, 9))
    # A ninth transition must not evict boot 1 and permit its delayed replay.
    for boot in (10, 1, 10):
        assert qualified(gate, sample(boot_id=boot, sample_ms=999),
                         102 + boot * .01, new_sample=False) == ()
        assert gate.last_boot_id == 9
        assert gate.retired_boot_ids == list(range(1, 9))
    # Current boot still supplies fresh samples; no new identity is trusted.
    assert qualified(gate, sample(boot_id=9, sample_ms=1000),
                     103, new_sample=False) == ()
    assert gate.last_boot_id == 9


def test_exhausted_boot_history_revokes_active_pose_without_evicting_replay_fence():
    gate = HandlingGate()
    for boot in range(1, 10):
        assert qualified(gate, sample(boot_id=boot, sample_ms=boot),
                         100 + boot * .1, new_sample=False) == ()
    for i in range(8):
        assert qualified(gate, sample(boot_id=9, sample_ms=20 + i),
                         102 + i * .1, new_sample=False) == ()
    assert gate.reference is not None
    assert gate.retired_boot_ids == list(range(1, 9))
    # Unknown generation may be a real WROOM reboot. Do not retain pose.
    assert qualified(gate, sample(boot_id=10, sample_ms=1),
                     104, new_sample=False) == ()
    assert gate.reference is None and gate.startup_samples == []
    assert gate.last_boot_id == 9
    assert gate.last_sample_ms == 27
    assert gate.retired_boot_ids == list(range(1, 9))
    # The same trusted conversion cannot seed a new baseline after revocation.
    assert qualified(gate, sample(boot_id=9, sample_ms=27),
                     104.05, new_sample=False) == ()
    assert gate.startup_samples == []
    # Retired replay cannot displace the source identity after revocation.
    assert qualified(gate, sample(boot_id=1, sample_ms=500),
                     104.1, new_sample=False) == ()
    assert gate.last_boot_id == 9


def test_out_of_order_host_callback_does_not_erase_newer_pose():
    gate = HandlingGate()
    calibrated(gate, 100)
    last_at = gate.last_at
    last_sample = gate.last_sample_ms
    assert gate.reference == (0, 0, 1)
    # An older callback can arrive after a newer physical conversion.
    # It must neither reset calibration nor advance source ownership.
    assert qualified(gate, sample(sample_ms=last_sample - 1),
                     last_at - .05, new_sample=False) == ()
    assert gate.reference == (0, 0, 1)
    assert gate.last_at == last_at
    assert gate.last_sample_ms == last_sample
    # A subsequent current conversion still belongs to the same pose.
    assert qualified(gate, sample(sample_ms=last_sample + 1),
                     last_at + .15, new_sample=False) == ()
    assert gate.reference == (0, 0, 1)
    # A genuine forward polling gap still invalidates calibration.
    assert qualified(gate, sample(sample_ms=last_sample + 2),
                     last_at + 1.5, new_sample=False) == ()
    assert gate.reference is None


def test_late_valid_conversion_after_host_gap_cannot_erase_pose():
    gate = HandlingGate()
    calibrated(gate, 100)
    assert gate.reference == (0, 0, 1)
    previous_at, previous_sample = gate.last_at, gate.last_sample_ms
    # Delivery after a long host delay is not a new physical conversion.
    assert qualified(gate, sample(sample_ms=previous_sample - 1),
                     previous_at + 2.0, new_sample=False) == ()
    assert gate.reference == (0, 0, 1)
    assert gate.last_at == previous_at
    assert gate.last_sample_ms == previous_sample
    # A genuinely newer conversion after that gap must revoke the pose.
    assert qualified(gate, sample(sample_ms=previous_sample + 1),
                     previous_at + 2.1, new_sample=False) == ()
    assert gate.reference is None


def test_corrupted_delayed_conversion_does_not_revoke_newer_pose():
    gate = HandlingGate()
    calibrated(gate, 100)
    previous_at, previous_sample = gate.last_at, gate.last_sample_ms
    old = sample(sample_ms=previous_sample - 1, valid=False)
    assert qualified(gate, old, previous_at + 2, new_sample=False) == ()
    assert gate.reference == (0, 0, 1)
    assert gate.last_at == previous_at
    assert gate.last_sample_ms == previous_sample
    # A malformed CURRENT conversion is not a harmless old callback.
    current = sample(sample_ms=previous_sample + 1, valid=False)
    assert qualified(gate, current, previous_at + 2.1,
                     new_sample=False) == ()
    assert gate.reference is None


def test_delayed_conversion_with_motor_activity_still_revokes_pose():
    gate = HandlingGate()
    calibrated(gate, 100)
    previous_at, previous_sample = gate.last_at, gate.last_sample_ms
    old = sample(sample_ms=previous_sample - 1, valid=False, left=1)
    assert qualified(gate, old, previous_at + .1, new_sample=False) == ()
    assert gate.reference is None


def test_out_of_order_motor_active_status_revokes_handling_pose():
    gate = HandlingGate()
    calibrated(gate, 100)
    previous_at, previous_sample = gate.last_at, gate.last_sample_ms
    assert gate.reference is not None
    # Host callback time can be older even when WROOM reports motor motion.
    # It must not preserve a stationary handling baseline.
    assert qualified(gate, sample(sample_ms=previous_sample - 1, left=1),
                     previous_at - .05, new_sample=False) == ()
    assert gate.reference is None
    assert gate.last_sample_ms == previous_sample


def test_new_boot_with_older_host_timestamp_revokes_calibration():
    gate = HandlingGate()
    calibrated(gate, 100)
    previous_at, previous_sample = gate.last_at, gate.last_sample_ms
    assert gate.reference is not None
    # Host callbacks may be delivered out of order across a WROOM reboot.
    # A new boot must never retain the previous boot's handling pose.
    assert qualified(gate, sample(boot_id=2, sample_ms=1),
                     previous_at - .05, new_sample=False) == ()
    assert gate.reference is None
    assert gate.last_boot_id == 2
    assert 1 in gate.retired_boot_ids
    # Delayed previous-boot samples cannot revive the old calibration.
    assert qualified(gate, sample(boot_id=1, sample_ms=previous_sample + 1),
                     previous_at + .15, new_sample=False) == ()
    assert gate.reference is None

def test_older_host_timestamp_cannot_hide_malformed_new_acquisition():
    gate = HandlingGate()
    calibrated(gate, 100)
    previous_at, previous_sample = gate.last_at, gate.last_sample_ms
    assert gate.reference is not None
    # Host callbacks may arrive out of order. A fresh but invalid WROOM
    # conversion must not be ignored merely because its host time is older.
    corrupt = sample(sample_ms=previous_sample + 1, valid=False)
    assert qualified(gate, corrupt, previous_at - .05, new_sample=False) == ()
    assert gate.reference is None
    assert gate.startup_samples == []
    # A genuinely old stationary acquisition is still harmless.
    assert qualified(gate, sample(sample_ms=previous_sample), previous_at - .1,
                     new_sample=False) == ()
    assert gate.reference is None


def test_new_acquisition_with_older_host_time_does_not_rewind_gate_clock():
    gate = HandlingGate()
    calibrated(gate, 100)
    previous_at, previous_sample = gate.last_at, gate.last_sample_ms
    assert qualified(gate, sample(sample_ms=previous_sample + 1),
                     previous_at - .05, new_sample=False) == ()
    assert gate.last_sample_ms == previous_sample + 1
    assert gate.last_at == previous_at
    # A truly later host polling gap must still revoke the pose.
    assert qualified(gate, sample(sample_ms=previous_sample + 2),
                     previous_at + 1.1, new_sample=False) == ()
    assert gate.reference is None


def test_missing_gyro_bias_revokes_pose_without_replaying_same_conversion():
    gate = HandlingGate()
    for i in range(8):
        assert qualified(gate, sample(sample_ms=3000 + i),
                         100 + i * .1, new_sample=False) == ()
    assert gate.reference is not None
    gate.gyro_bias_dps = None  # Corrupted/incomplete host calibration state.
    current = sample(sample_ms=3008)
    assert qualified(gate, current, 101.0, new_sample=False) == ()
    assert gate.reference is None
    assert gate.last_boot_id == 1 and gate.last_sample_ms == 3008
    for i in range(8):
        assert qualified(gate, current, 101.1 + i * .1,
                         new_sample=False) == ()
    assert gate.startup_samples == []
    assert qualified(gate, sample(sample_ms=3009),
                     102.0, new_sample=False) == ()
    assert len(gate.startup_samples) == 1


def test_backdated_fresh_acquisitions_cannot_shorten_shake_cooldown():
    gate = HandlingGate()
    calibrated(gate, 100)
    last_at, last_sample = gate.last_at, gate.last_sample_ms
    # A newer conversion may carry an older callback time; cooldowns must
    # use the monotonic accepted clock rather than that callback time.
    for i in range(2):
        frame = sample(acc=(0, 0, 26000), gyro=(16500, 0, 0),
                       sample_ms=last_sample + i + 1)
        expected = ("handling_shake",) if i == 1 else ()
        assert qualified(gate, frame, last_at - .1 + .01 * i,
                         new_sample=False) == expected
    assert gate.last_shake == last_at
    for i in range(1, 6):
        assert qualified(gate, sample(sample_ms=last_sample + i + 2),
                         last_at + .5 * i, new_sample=False) == ()
    for i, delta in enumerate((2.6, 2.7), start=8):
        frame = sample(acc=(0, 0, 26000), gyro=(16500, 0, 0),
                       sample_ms=last_sample + i)
        assert qualified(gate, frame, last_at + delta,
                         new_sample=False) == ()
    assert gate.last_shake == last_at


def test_invalid_imu_does_not_restart_recent_shake_cooldown():
    gate = HandlingGate()
    calibrated(gate)
    shake = sample(acc=(0, 0, 26000), gyro=(16500, 0, 0))
    assert qualified(gate, shake, 102.0) == ()
    assert qualified(gate, shake, 102.15) == ("handling_shake",)
    assert qualified(gate, sample(valid=False), 102.2) == ()
    assert gate.reference is None
    calibrated(gate, 102.3)
    assert qualified(gate, shake, 103.6) == ()
    assert qualified(gate, shake, 103.75) == ()
    assert gate.last_shake == 102.15
    for when in (104.0, 104.5, 105.0):
        assert qualified(gate, sample(), when) == ()
    assert qualified(gate, shake, 105.2) == ()
    assert qualified(gate, shake, 105.35) == ("handling_shake",)


def test_poll_gap_recalibration_cannot_bypass_shake_cooldown():
    gate = HandlingGate()
    calibrated(gate, 100)
    shaking = sample(acc=(0, 0, 26000), gyro=(16500, 0, 0))
    assert qualified(gate, shaking, 102.0) == ()
    assert qualified(gate, shaking, 102.15) == ("handling_shake",)
    # A new acquisition after a transport gap revokes pose but must not
    # reset the independent three-second gesture cooldown.
    assert qualified(gate, sample(), 103.2) == ()
    assert gate.reference is None
    assert gate.last_shake == 102.15
    for i in range(7):
        assert qualified(gate, sample(), 103.35 + i * .15) == ()
    assert gate.reference is not None
    assert qualified(gate, shaking, 104.45) == ()
    assert qualified(gate, shaking, 104.60) == ()
    assert gate.last_shake == 102.15


def test_mpu_clock_rollover_preserves_shake_cooldown():
    gate = HandlingGate()
    # Establish a legitimate near-wrap acquisition and stationary baseline.
    for i in range(8):
        assert qualified(gate, sample(sample_ms=0xfffffff0 + i),
                         100.0 + .1 * i, new_sample=False) == ()
    assert gate.reference is not None
    gate.last_shake = 100.7  # An already announced gesture.
    assert qualified(gate, sample(sample_ms=2), 100.8,
                     new_sample=False) == ()
    assert gate.reference is None  # Rollover requires a new pose baseline.
    assert gate.last_shake == 100.7  # But must not bypass cooldown.
    for i in range(7):
        assert qualified(gate, sample(sample_ms=3 + i),
                         100.9 + .1 * i, new_sample=False) == ()
    assert gate.reference is not None
    shaking = sample(acc=(0, 0, 26000), gyro=(16500, 0, 0))
    assert qualified(gate, dict(shaking, imu=dict(shaking["imu"], sample_ms=10)),
                     101.7, new_sample=False) == ()
    assert qualified(gate, dict(shaking, imu=dict(shaking["imu"], sample_ms=11)),
                     101.8, new_sample=False) == ()
    assert gate.last_shake == 100.7


def test_new_boot_recalibration_preserves_recent_shake_cooldown():
    gate = HandlingGate()
    calibrated(gate, 100)
    shaking = sample(acc=(0, 0, 26000), gyro=(16500, 0, 0))
    assert qualified(gate, shaking, 102.0) == ()
    assert qualified(gate, shaking, 102.15) == ("handling_shake",)
    assert qualified(gate, sample(boot_id=2, sample_ms=1), 102.3, new_sample=False) == ()
    assert gate.reference is None
    assert gate.last_shake == 102.15
    for i in range(2, 9):
        assert qualified(gate, sample(boot_id=2, sample_ms=i),
                         102.3 + (i - 1) * .15, new_sample=False) == ()
    assert gate.reference is not None
    for i, when in enumerate((103.5, 103.65), start=9):
        frame = sample(acc=(0, 0, 26000), gyro=(16500, 0, 0),
                       boot_id=2, sample_ms=i)
        assert qualified(gate, frame, when, new_sample=False) == ()
    assert gate.last_shake == 102.15


def test_implausible_acceleration_recalibration_preserves_shake_cooldown():
    gate = HandlingGate()
    calibrated(gate)
    shaking = sample(acc=(0, 0, 26000), gyro=(16500, 0, 0))
    assert qualified(gate, shaking, 102.0) == ()
    assert qualified(gate, shaking, 102.15) == ("handling_shake",)
    # Fresh but physically implausible near-zero acceleration must revoke
    # the pose without granting another unsolicited gesture immediately.
    assert qualified(gate, sample(acc=(0, 0, 0)), 102.3) == ()
    assert gate.reference is None
    assert gate.last_shake == 102.15
    for i in range(8):
        assert qualified(gate, sample(), 102.45 + .15 * i) == ()
    assert gate.reference is not None
    assert qualified(gate, shaking, 103.7) == ()
    assert qualified(gate, shaking, 103.85) == ()
    assert gate.last_shake == 102.15

def test_qualification_revoke_keeps_shake_cooldown():
    """A temporary source fault must not repeat a proactive shake greeting."""
    gate = HandlingGate()
    calibrated(gate)
    shaking = sample(acc=(0, 0, 26000), gyro=(16500, 0, 0))
    assert qualified(gate, shaking, 102.0) == ()
    assert qualified(gate, shaking, 102.15) == ("handling_shake",)
    assert gate.last_shake == pytest.approx(102.15)

    # Even a temporarily disabled physical profile revokes pose, not the
    # human facing event cooldown. Explicit reset() still starts a new session.
    assert gate.observe(sample(), 102.2, qualified=False) == ()
    assert gate.reference is None
    assert gate.last_shake == pytest.approx(102.15)
    for i in range(8):
        assert qualified(gate, sample(), 102.3 + i * 0.1) == ()
    assert gate.reference is not None
    assert qualified(gate, shaking, 103.2) == ()
    assert qualified(gate, shaking, 103.3) == ()
    assert gate.last_shake == pytest.approx(102.15)
    # Wait for the original three second host cooldown without gaps that
    # would trigger a fresh calibration.
    for when in (103.6, 104.0, 104.4, 104.8, 105.1):
        assert qualified(gate, sample(), when) == ()
    assert qualified(gate, shaking, 105.2) == ()
    assert qualified(gate, shaking, 105.3) == ("handling_shake",)

    gate.reset()
    assert gate.last_shake == -float("inf")

@pytest.mark.parametrize("fault,when", [
    ("invalid_imu", 102.3),
    ("sensor_gap", 104.0),
    ("new_boot", 102.3),
    ("implausible_gravity", 102.3),
])
def test_fault_reboots_and_gaps_preserve_prior_shake_cooldown(fault, when):
    """Fault invalidation cannot unlock the same physical shake repeatedly."""
    gate = HandlingGate()
    calibrated(gate)
    moving = sample(acc=(0, 0, 26000), gyro=(16500, 0, 0))
    assert qualified(gate, moving, 102.0) == ()
    assert qualified(gate, moving, 102.15) == ("handling_shake",)
    observed = gate.last_shake
    if fault == "invalid_imu":
        changed = sample(valid=False)
    elif fault == "sensor_gap":
        changed = sample()
    elif fault == "new_boot":
        changed = sample(boot_id=2)
    else:
        changed = sample(acc=(0, 0, 0))
    assert qualified(gate, changed, when) == ()
    assert gate.last_shake == pytest.approx(observed)
    assert gate.reference is None


def test_cached_imu_conversion_after_reconnect_cannot_repeat_recent_shake():
    """A one-second host gap invalidates pose, not the human shake cooldown."""
    gate = HandlingGate()
    calibrated(gate)
    shaking = sample(acc=(0, 0, 26000), gyro=(16500, 0, 0))
    assert qualified(gate, shaking, 102.0) == ()
    assert qualified(gate, shaking, 102.15) == ("handling_shake",)
    assert gate.last_shake == 102.15
    # Reconnected status reuses the last physical sample even though its
    # host timestamp is new. It cannot create a new shake or clear cooldown.
    cached = sample(sample_ms=gate.last_sample_ms)
    assert qualified(gate, cached, 103.25, new_sample=False) == ()
    assert gate.reference is None
    assert gate.last_shake == 102.15
    for i in range(8):
        assert qualified(gate, sample(), 103.35 + i * 0.10) == ()
    assert gate.reference is not None
    assert qualified(gate, shaking, 104.25) == ()
    assert qualified(gate, shaking, 104.40) == ()
    assert gate.last_shake == 102.15


def test_conflicting_stationary_calibration_norm_keeps_shake_cooldown():
    """Physically inconsistent 1g baselines cannot reannounce a recent shake."""
    gate = HandlingGate()
    calibrated(gate)
    shaking = sample(acc=(0, 0, 26000), gyro=(16500, 0, 0))
    assert qualified(gate, shaking, 102.0) == ()
    assert qualified(gate, shaking, 102.15) == ("handling_shake",)
    # Invalid actual IMU identity revokes pose, then eight individually
    # plausible, alternating 1g readings have a near-zero aggregate norm.
    assert qualified(gate, sample(family=3), 102.20) == ()
    for i in range(8):
        z = 16384 if i % 2 == 0 else -16384
        assert qualified(gate, sample(acc=(0, 0, z)),
                         102.30 + i * 0.10) == ()
    assert gate.reference is None
    assert gate.startup_samples == []
    assert gate.last_shake == 102.15
    for i in range(8):
        assert qualified(gate, sample(), 103.10 + i * 0.10) == ()
    assert gate.reference is not None
    assert qualified(gate, shaking, 104.0) == ()
    assert qualified(gate, shaking, 104.15) == ()
    assert gate.last_shake == 102.15


def test_explicit_session_restart_recovers_exhausted_imu_boot_history():
    """Operator restart reopens observation, never reuses old pose evidence."""
    gate = HandlingGate()
    for boot in range(1, 10):
        assert qualified(
            gate, sample(boot_id=boot, sample_ms=boot),
            100 + boot * 0.1, new_sample=False,
        ) == ()
    assert gate.retired_boot_ids == list(range(1, 9))
    assert qualified(
        gate, sample(boot_id=10, sample_ms=1),
        102, new_sample=False,
    ) == ()
    assert gate.last_boot_id == 9
    gate.reset()
    assert gate.retired_boot_ids == []
    assert gate.last_boot_id is None
    assert gate.reference is None
    assert gate.last_shake == float("-inf")
    # A new operator session must collect a fresh eight-conversion
    # stationary reference rather than inherit a pose from the old boot.
    for i in range(8):
        assert qualified(
            gate, sample(boot_id=10, sample_ms=i + 1),
            105 + i * 0.1, new_sample=False,
        ) == ()
    assert gate.reference == (0, 0, 1)


def test_internal_handling_reset_keeps_retired_boot_replay_fence():
    """Sensor faults preserve earlier boot identities until operator reset."""
    gate = HandlingGate()
    for boot in (1, 2, 3):
        assert qualified(
            gate, sample(boot_id=boot, sample_ms=boot),
            100 + boot * 0.1, new_sample=False,
        ) == ()
    assert gate.retired_boot_ids == [1, 2]
    gate.reset(preserve_shake_cooldown=True)
    assert gate.retired_boot_ids == [1, 2]
    assert qualified(
        gate, sample(boot_id=1, sample_ms=4000),
        102, new_sample=False,
    ) == ()
    assert gate.reference is None
    assert gate.startup_samples == []


def test_read_only_mpu_temperature_requires_fresh_attested_stationary_sample():
    frame = canonical_wroom_sample()
    frame["imu"].update(temp_raw=-1286, temp_valid=True)
    assert mpu6050_temperature_raw(frame) == -1286
    frame["imu"]["temp_raw"] = 344
    assert mpu6050_temperature_raw(frame) == 344
    for malformed in (None, True, 1.2, "344", 32768, -32769):
        frame["imu"]["temp_raw"] = malformed
        assert mpu6050_temperature_raw(frame) is None
    frame["imu"]["temp_raw"] = 344
    frame["imu"]["temp_valid"] = False
    assert mpu6050_temperature_raw(frame) is None
    frame["imu"]["temp_valid"] = True
    frame["imu"]["age_ms"] = 201
    assert mpu6050_temperature_raw(frame) is None
    frame["imu"]["age_ms"] = 20
    frame["motor"]["m0"] = 10
    assert mpu6050_temperature_raw(frame) is None
    frame["motor"]["m0"] = 0
    frame["imu"]["family"] = 1
    assert mpu6050_temperature_raw(frame) is None


def test_low_g_revokes_stale_mount_pose_without_arming_or_fake_drop():
    """Physical low-g evidence invalidates a relative pose, not motor safety."""
    gate = HandlingGate()
    calibrated(gate)
    assert gate.reference == (0, 0, 1)
    gate.last_shake = 100.8
    low_g = sample(acc=(0, 0, 4096), sample_ms=102000)
    assert qualified(gate, low_g, 102.0, new_sample=False) == ()
    assert gate.reference is None
    assert gate.gyro_bias_dps is None
    assert gate.last_sample_ms == 102000
    assert gate.last_shake == 100.8
    # Replayed evidence cannot seed even the first stationary sample.
    assert qualified(gate, low_g, 102.1, new_sample=False) == ()
    assert gate.startup_samples == []
    # The next source acquisitions must first establish eight independent
    # stationary observations before relative tilt can be used again.
    for i in range(8):
        assert qualified(gate, sample(), 102.2 + i * 0.1) == ()
    assert gate.reference == (0, 0, 1)


def test_nonzero_low_g_below_pose_invalidation_boundary_revokes_reference():
    gate = HandlingGate()
    calibrated(gate)
    # Old code only revoked <=0.05g, preserving the pose after a credible
    # low-g interval. A little residual acceleration is not a stable mount.
    assert qualified(gate, sample(acc=(8191, 0, 0)), 102.0) == ()
    assert gate.reference is None
    calibrated(gate, 102.2)
    # Values at the conservative invalidation boundary are still dynamic,
    # and cannot be used to generate a static tilt announcement.
    assert qualified(gate, sample(acc=(8192, 0, 0)), 104.0) == ()
    assert gate.reference is not None
    assert gate.tilt_hits == 0


def _mpu_native_low_g(seq, *, irq=False, valid=True, boot_id=1):
    frame = sample(boot_id=boot_id)
    frame["imu"].update(low_g_valid=valid, low_g_irq=irq, low_g_seq=seq)
    return frame


def test_hardware_low_g_counter_survives_missing_host_pulse():
    """Mac may read after the FF_INT pulse, while WROOM seq retains it."""
    gate = HandlingGate()
    calibrated(gate)
    assert qualified(gate, _mpu_native_low_g(0), 102.0) == ()
    assert gate.reference == (0, 0, 1)
    event = _mpu_native_low_g(1, irq=False)
    assert qualified(gate, event, 102.2) == ()
    assert gate.reference is None
    assert gate.last_low_g_seq == 1
    assert gate.last_sample_ms == event["imu"]["sample_ms"]
    # A cached HTTP/UART status cannot seed calibration or be seen twice.
    assert qualified(gate, event, 102.3, new_sample=False) == ()
    assert gate.startup_samples == []
    for i in range(8):
        assert qualified(gate, _mpu_native_low_g(1),
                         102.4 + 0.1 * i) == ()
    assert gate.reference == (0, 0, 1)
    assert qualified(gate, _mpu_native_low_g(1, irq=True),
                     103.25) == ()
    # Deduplicating the event counter must not treat an asserted interrupt
    # as trustworthy upright evidence.
    assert gate.reference is None
    assert gate.startup_samples == []
    assert qualified(gate, _mpu_native_low_g(2), 103.4) == ()
    assert gate.reference is None
    assert gate.last_low_g_seq == 2
    assert gate.observe(_mpu_native_low_g(2), 103.5, qualified=False) == ()
    assert gate.last_low_g_seq == 2  # requalify cannot replay old event


def test_native_low_g_status_faults_revoke_pose_and_preserve_event_fence():
    gate = HandlingGate()
    calibrated(gate)
    assert qualified(gate, _mpu_native_low_g(4), 102) == ()
    assert gate.last_low_g_seq == 4
    for override in (
        {"low_g_valid": True, "low_g_irq": True, "low_g_seq": 0},
        {"low_g_valid": True, "low_g_irq": False, "low_g_seq": 3},
        {"low_g_valid": 1, "low_g_irq": False, "low_g_seq": 4},
        {"low_g_valid": False, "low_g_irq": True, "low_g_seq": 4},
        {"low_g_valid": True, "low_g_irq": False, "low_g_seq": 0x100000000},
    ):
        gate.reset(preserve_shake_cooldown=True)
        gate.last_low_g_seq = 4
        for i in range(8):
            assert qualified(gate, _mpu_native_low_g(4), 103 + i * 0.1) == ()
        assert gate.reference is not None
        frame = _mpu_native_low_g(4)
        frame["imu"].update(override)
        assert qualified(gate, frame, 105) == ()
        assert gate.reference is None
        assert gate.last_low_g_seq == 4
    gate.reset()
    assert gate.last_low_g_seq is None


def test_low_g_status_read_failure_cannot_erase_counter_or_claim_event():
    gate = HandlingGate()
    calibrated(gate)
    assert qualified(gate, _mpu_native_low_g(0), 102.0) == ()
    assert qualified(gate, _mpu_native_low_g(1, valid=False), 102.2) == ()
    assert gate.reference is None  # unknown FF status cannot preserve upright pose
    assert gate.last_low_g_seq == 0
    assert qualified(gate, _mpu_native_low_g(1), 102.4) == ()
    assert gate.reference is None  # the later valid counter reveals the IRQ
    assert gate.last_low_g_seq == 1
    # A genuinely new MCU boot may restart its native interrupt counter.
    assert qualified(gate, _mpu_native_low_g(0, boot_id=2),
                     102.6) == ()
    assert gate.last_low_g_seq == 0
    assert gate.last_boot_id == 2


@pytest.mark.parametrize("next_boot", [1, 2])
def test_native_low_g_metadata_cannot_be_silently_downgraded(next_boot):
    gate = HandlingGate()
    calibrated(gate)
    assert qualified(gate, _mpu_native_low_g(0), 102.0) == ()
    assert gate.reference is not None
    assert gate.native_low_g_seen

    # Every fresh frame is otherwise stationary and valid, but none
    # provides the native FF status already attested by this session.
    for i in range(9):
        frame = sample(boot_id=next_boot)
        assert qualified(gate, frame, 102.2 + i * 0.1) == ()
        assert gate.reference is None
        assert gate.startup_samples == []
    assert gate.native_low_g_seen

    # Restoring complete metadata allows a new eight-conversion baseline.
    for i in range(8):
        frame = _mpu_native_low_g(0, boot_id=next_boot)
        assert qualified(gate, frame, 103.2 + i * 0.1) == ()
    assert gate.reference == (0, 0, 1)
    gate.reset()
    assert not gate.native_low_g_seen
    calibrated(gate, 105)


def test_partial_native_low_g_status_also_fences_legacy_downgrade():
    gate = HandlingGate()
    frame = sample()
    frame["imu"]["low_g_valid"] = False
    assert qualified(gate, frame, 100.0) == ()
    assert gate.native_low_g_seen
    for i in range(8):
        assert qualified(gate, sample(), 100.2 + i * 0.1) == ()
    assert gate.reference is None
    assert gate.startup_samples == []


def test_asserted_native_low_g_cannot_seed_upright_calibration():
    gate = HandlingGate()
    calibrated(gate)
    assert qualified(gate, _mpu_native_low_g(0), 102.0) == ()
    assert qualified(gate, _mpu_native_low_g(1, irq=True), 102.1) == ()
    for i in range(10):
        assert qualified(gate, _mpu_native_low_g(1, irq=True), 102.2 + i * 0.1) == ()
        assert gate.reference is None
        assert gate.startup_samples == []
        assert gate.last_low_g_seq == 1
    for i in range(7):
        assert qualified(gate, _mpu_native_low_g(1), 103.2 + i * 0.1) == ()
        assert gate.reference is None
    assert qualified(gate, _mpu_native_low_g(1), 103.9) == ()
    assert gate.reference == (0, 0, 1)


@pytest.mark.parametrize("valid", [True, False])
def test_delayed_pre_wrap_packet_cannot_revoke_pose_after_poll_gap(valid):
    gate = HandlingGate()
    for i in range(8):
        assert qualified(gate, sample(sample_ms=2 + i), 100 + i * .1,
                         new_sample=False) == ()
    previous_at = gate.last_at
    assert gate.reference == (0, 0, 1)
    assert qualified(gate, sample(sample_ms=0xfffffffe, valid=valid),
                     previous_at + 2, new_sample=False) == ()
    assert gate.reference == (0, 0, 1)
    assert gate.last_at == previous_at
    assert gate.last_sample_ms == 9
    assert qualified(gate, sample(sample_ms=10), previous_at + 2.1,
                     new_sample=False) == ()
    assert gate.reference is None


@pytest.mark.parametrize("offset", [-.05, 0])
def test_new_rollover_acquisition_with_late_callback_revokes_pose(offset):
    gate = HandlingGate()
    for i in range(8):
        assert qualified(gate, sample(sample_ms=0xfffffff0 + i), 100 + i * .1,
                         new_sample=False) == ()
    previous_at = gate.last_at
    gate.last_shake = previous_at
    assert qualified(gate, sample(sample_ms=2), previous_at + offset,
                     new_sample=False) == ()
    assert gate.reference is None
    assert gate.last_sample_ms == 2
    assert gate.last_at == previous_at
    assert gate.last_shake == previous_at
    assert len(gate.startup_samples) == 1


def test_pre_wrap_motor_active_still_revokes_pose():
    gate = HandlingGate()
    for i in range(8):
        qualified(gate, sample(sample_ms=2 + i), 100 + i * .1, new_sample=False)
    assert gate.reference is not None
    assert qualified(gate, sample(sample_ms=0xfffffffe, left=1), 103,
                     new_sample=False) == ()
    assert gate.reference is None

@pytest.mark.parametrize(("elapsed_ms", "accepted"), [
    (0, True), (20, True), (20.01, False), (200, False),
    (-1, False), (True, False), (float("nan"), False),
    (float("inf"), False), ("20", False),
    pytest.param(10**400, False, id="huge-int"),
])
def test_source_age_plus_transport_age(elapsed_ms, accepted):
    frame = canonical_wroom_sample(age=180, sample_ms=1000, gyro=(0, 131, 0))
    assert (raw_mpu6050(frame, request_elapsed_ms=elapsed_ms) is not None) is accepted
    assert frame["imu"]["age_ms"] == 180


def test_stale_delivered_imu_cannot_confirm_handling_tilt():
    gate = HandlingGate()
    calibrated(gate)
    first = canonical_wroom_sample(acc=(12551, 0, 10531), sample_ms=101200)
    assert gate.observe(
        first, 101.2, qualified=True, calibrated=True, request_elapsed_ms=10,
    ) == ()
    late = canonical_wroom_sample(acc=(12551, 0, 10531), sample_ms=101400, age=180)
    assert gate.observe(
        late, 101.4, qualified=True, calibrated=True, request_elapsed_ms=30,
    ) == ()
    assert gate.reference is None


@pytest.mark.parametrize("backdated", [False, True])
@pytest.mark.parametrize(
    ("variant", "should_revoke"),
    [
        ("duplicate", False),
        ("irq_seq_advance", True),
        ("invalid_flag", True),
        ("omitted_native", True),
    ],
)
def test_same_acquisition_conflicting_native_low_g_revokes_pose(
    backdated, variant, should_revoke,
):
    gate = HandlingGate()
    for i in range(8):
        frame = _mpu_native_low_g(0, irq=False, valid=True, boot_id=1)
        assert qualified(gate, frame, 100.0 + i * 0.1) == ()
    assert gate.reference == (0, 0, 1)
    previous_at = gate.last_at
    gate.last_shake = previous_at
    last_stamp = gate.last_sample_ms

    replay = _mpu_native_low_g(0, irq=False, valid=True, boot_id=1)
    replay["imu"]["sample_ms"] = last_stamp
    if variant == "irq_seq_advance":
        replay["imu"].update(low_g_valid=True, low_g_irq=True, low_g_seq=1)
    elif variant == "invalid_flag":
        replay["imu"].update(low_g_valid=False, low_g_irq=False, low_g_seq=0)
    elif variant == "omitted_native":
        for key in ("low_g_valid", "low_g_irq", "low_g_seq"):
            replay["imu"].pop(key, None)

    observe_at = previous_at - 0.05 if backdated else previous_at + 0.05
    assert qualified(gate, replay, observe_at, new_sample=False) == ()
    assert gate.last_shake == previous_at
    assert gate.last_at == previous_at
    if should_revoke:
        assert gate.reference is None
        assert gate.startup_samples == []
    else:
        assert gate.reference == (0, 0, 1)


@pytest.mark.parametrize("magnitude,accepted", [
    (0.909, False), (0.91, True), (1.0, True), (1.09, True), (1.091, False),
])
def test_gravity_reference_magnitude_boundaries(magnitude, accepted):
    reference = handling._gravity_reference([(magnitude, 0.0, 0.0)] * 8)
    assert (reference is not None) is accepted
    if accepted:
        assert reference == pytest.approx((1.0, 0.0, 0.0))
    assert handling._gravity_reference([(1.0, 0.0, 0.0), (-1.0, 0.0, 0.0)] * 4) is None


@pytest.mark.parametrize("angle", [0, 19, 37.9, 38.1, 90, 179.9, 180])
@pytest.mark.parametrize("rotation", [0, 23, 90, 137, 270])
def test_relative_tilt_is_rotation_and_scale_invariant(angle, rotation):
    theta = math.radians(rotation)
    delta = math.radians(angle)
    reference = (math.cos(theta), math.sin(theta), 0.0)
    for magnitude in (0.75, 1.0, 1.25):
        acceleration = (
            magnitude * math.cos(theta + delta), magnitude * math.sin(theta + delta), 0.0,
        )
        assert handling._relative_tilt_degrees(
            acceleration, reference, math.hypot(*acceleration),
        ) == pytest.approx(angle, abs=2e-6)


@pytest.mark.parametrize("axes", list(permutations(range(3))))
@pytest.mark.parametrize("first_sign,second_sign", list(product((-1, 1), repeat=2)))
def test_handling_events_invariant_under_proper_axis_remapping(axes, first_sign, second_sign):
    inversions = sum(axes[i] > axes[j] for i in range(3) for j in range(i + 1, 3))
    signs = (first_sign, second_sign, (-1) ** inversions * first_sign * second_sign)

    def rotate(vector):
        return tuple(sign * vector[axis] for sign, axis in zip(signs, axes, strict=True))

    gate = HandlingGate()
    tick = 0

    def observe(acc, gyro=(80, -40, 60)):
        nonlocal tick
        tick += 1
        return qualified(gate, sample(acc=rotate(acc), gyro=rotate(gyro)), 100 + tick * 0.1)

    # Balanced quantized noise exercises both startup and ongoing stationarity.
    for i in range(8):
        sign = (-1) ** i
        assert observe((120 * sign, -80 * sign, 16384 + 60 * sign),
                       (80 + 20 * sign, -40, 60 - 10 * sign)) == ()
    assert gate.reference == pytest.approx(rotate((0, 0, 1)))
    for i in range(20):
        sign = (-1) ** i
        assert observe((300 * sign, 140 * sign, 16384 + 200 * sign),
                       (80 + 30 * sign, -40, 60)) == ()
    assert observe((10000, 0, 12979)) == ()  # below the 38 degree boundary
    assert observe((12551, 0, 10531)) == ()
    assert observe((12551, 0, 10531)) == ("handling_tilt",)
    assert observe((12551, 0, 10531)) == ()  # held tilt is not another edge
    assert observe((0, 0, 16384)) == ()
    assert observe((12551, 0, 10531)) == ()
    assert observe((12551, 0, 10531)) == ("handling_tilt",)
    assert observe((0, 0, 26000), (80, -40, 60)) == ()  # acceleration only
    assert observe((0, 0, 26000), (80, -40, 60)) == ()
    assert observe((0, 0, 16384), (16500, 0, 0)) == ()  # gyro only
    assert observe((0, 0, 16384), (16500, 0, 0)) == ()
    assert observe((0, 0, 26000), (16500, 0, 0)) == ()
    assert observe((0, 0, 26000), (16500, 0, 0)) == ("handling_shake",)
    assert observe((0, 0, 26000), (16500, 0, 0)) == ()  # cooldown
    assert gate.reference == pytest.approx(rotate((0, 0, 1)))
