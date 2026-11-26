"""Motor activity must fence cached IMU conversions before handling calibration."""

import pytest
from desk_robot.handling import HandlingGate, raw_mpu6050


def frame(stamp, *, moving=False, boot=1, acc=(0, 0, 16384), gyro=(0, 0, 0)):
    return {
        "motor": {"m0": 40 if moving else 0, "m1": -40 if moving else 0},
        "drive_ms": 250 if moving else 0,
        "imu": {
            "family": 4, "gyro_id": 0x68, "valid": True, "age_ms": 20,
            "boot_id": boot, "sample_ms": stamp, "acc": list(acc),
            "gyro": list(gyro), "low_g_valid": True, "low_g_irq": False,
            "low_g_seq": 0,
        },
    }


@pytest.mark.parametrize("boot", [1, 2])
def test_drive_conversion_cannot_seed_stationary_calibration(boot):
    gate = HandlingGate()
    for i in range(8):
        assert gate.observe(frame(100 + i * 50), 1 + i * .05, qualified=True, calibrated=True) == ()
    assert gate.reference == (0, 0, 1)
    # An otherwise quiet conversion acquired during motor activity is not
    # evidence of a stationary pose, even after the drive lease ends.
    active = frame(500, moving=True, boot=boot)
    assert raw_mpu6050(active) is None
    assert gate.observe(active, 1.4, qualified=True, calibrated=True) == ()
    assert gate.reference is None
    assert gate.observe(frame(500, boot=boot), 1.45, qualified=True, calibrated=True) == ()
    assert gate.startup_samples == []
    for i in range(7):
        assert gate.observe(frame(550 + i * 50, boot=boot), 1.5 + i * .05,
                            qualified=True, calibrated=True) == ()
    assert gate.reference is None
    assert gate.observe(frame(900, boot=boot), 1.85, qualified=True, calibrated=True) == ()
    assert gate.reference == (0, 0, 1)
    # Fresh stationary tilt still produces contextual evidence, not a stop
    # command or a verified pickup. Firmware remains the motion authority.
    tilted = (12551, 0, 10531)
    assert gate.observe(
        frame(950, boot=boot, acc=tilted), 1.9, qualified=True, calibrated=True,
    ) == ()
    assert gate.observe(frame(1000, boot=boot, acc=tilted), 1.95,
                        qualified=True, calibrated=True) == ("handling_tilt",)


def test_drive_vibration_and_reordered_motor_status_revoke_pose():
    gate = HandlingGate()
    for i in range(8):
        gate.observe(frame(100 + i * 50), 1 + i * .05, qualified=True, calibrated=True)
    assert gate.reference is not None
    for i in range(4):
        active = frame(500 + i * 50, moving=True, acc=(0, 0, 26000),
                       gyro=(16500, 0, 0))
        assert gate.observe(active, 1.4 + i * .05, qualified=True, calibrated=True) == ()
    assert gate.reference is None
    assert gate.startup_samples == []
    # Neither the last driving conversion nor an older one can seed pose.
    for stamp in (650, 600):
        assert gate.observe(frame(stamp), 1.7, qualified=True, calibrated=True) == ()
    assert gate.startup_samples == []
