"""Regression coverage for handling stage ordering and acquisition fences."""
from desk_robot.handling import HandlingGate


def frame(stamp, *, boot=1, motors=0, seq=0, irq=False, acc=(0, 0, 16384)):
    return {
        "motor": {"m0": motors, "m1": 0},
        "drive_ms": 250 if motors else 0,
        "imu": {
            "family": 4, "gyro_id": 0x68, "valid": True, "age_ms": 20,
            "boot_id": boot, "sample_ms": stamp, "acc": list(acc),
            "gyro": [0, 0, 0], "low_g_valid": True, "low_g_irq": irq,
            "low_g_seq": seq,
        },
    }


def observe(gate, sample, now):
    return gate.observe(sample, now, qualified=True, calibrated=True)


def calibrate(gate, *, start=1000, now=100.0, seq=0):
    for offset in range(8):
        assert observe(gate, frame(start + offset, seq=seq), now + offset * .1) == ()
    assert gate.reference == (0.0, 0.0, 1.0)
    assert gate.gyro_bias_dps == (0.0, 0.0, 0.0)


def test_conflicting_duplicate_revokes_before_backdated_replay_filter():
    gate = HandlingGate()
    calibrate(gate)
    previous_time = gate.last_at
    previous_native = gate.last_native_low_g
    assert observe(gate, frame(1007, seq=1, irq=True), 100.1) == ()
    assert gate.reference is None and gate.gyro_bias_dps is None
    assert (gate.last_boot_id, gate.last_sample_ms) == (1, 1007)
    assert gate.last_at == previous_time
    assert gate.last_low_g_seq == 1
    assert gate.last_native_low_g == previous_native
    assert gate.native_low_g_seen is True
    assert gate.startup_samples == []


def test_motor_active_acquisition_consumes_native_counter_without_seeding_pose():
    gate = HandlingGate()
    calibrate(gate)
    # Host time is older, but this is a fresh acquisition with a new IRQ count.
    assert observe(gate, frame(1008, motors=20, seq=1), 100.2) == ()
    assert gate.reference is None and gate.gyro_bias_dps is None
    assert (gate.last_boot_id, gate.last_sample_ms, gate.last_low_g_seq) == (1, 1008, 1)
    assert gate.last_native_low_g == (True, True, False, 1)
    # The exact conversion cannot be reused after the motors become stationary.
    assert observe(gate, frame(1008, seq=1), 100.8) == ()
    assert gate.startup_samples == []
    calibrate(gate, start=1009, now=100.9, seq=1)


def test_raw_axis_rejection_clears_snapshot_but_not_native_capability_or_identity():
    gate = HandlingGate()
    calibrate(gate)
    assert observe(gate, frame(1008, acc=(0, 0, 0)), 100.8) == ()
    assert gate.reference is None and gate.gyro_bias_dps is None
    assert (gate.last_boot_id, gate.last_sample_ms, gate.last_low_g_seq) == (1, 1008, 0)
    assert gate.last_native_low_g is None
    assert gate.native_low_g_seen is True
    legacy = frame(1009)
    for key in ("low_g_valid", "low_g_irq", "low_g_seq"):
        del legacy["imu"][key]
    assert observe(gate, legacy, 100.9) == ()
    assert gate.startup_samples == []
    assert gate.last_sample_ms == 1009
    calibrate(gate, start=1010, now=101.0)
