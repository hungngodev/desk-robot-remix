"""Source-grounded MPU6050 handling behavior, not physical calibration proof."""
import pytest
from desk_robot.handling import HandlingGate, raw_mpu6050


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


def qualified(gate, body, now, *, new_sample=True):
    if new_sample:
        body["imu"]["sample_ms"] = int(round(now * 1000)) & 0xffffffff
    return gate.observe(
        body, now, qualified=True,
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
        assert gate.observe(frame, 100.0, qualified=True) == ()
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


def test_imu_requires_eight_still_upright_baseline_reads():
    gate = HandlingGate()
    for i in range(7):
        assert qualified(gate, sample(), 100 + .15 * i) == ()
    assert gate.reference is None
    assert qualified(gate, sample(gyro=(2000, 0, 0)), 101.10) == ()
    assert gate.startup_samples == []  # rotating robot cannot set a baseline
    calibrated(gate, 102)
    assert gate.reference == (0, 0, 1)


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
