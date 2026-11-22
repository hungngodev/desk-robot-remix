"""USB bench must not misreport the WROOM's independent attitude guard as absent."""
import runpy
from pathlib import Path

import pytest

inspect = runpy.run_path(str(
    Path(__file__).resolve().parents[1] / "scripts/serial_bench.py"
))["inspect_status"]


def status(fault: str | None = "none") -> dict:
    return {
        "backend": "stepper_28byj48",
        "armed": False,
        "touch": {"active": False},
        "safety": {"ready": False, "fault": fault, "sensor": 255},
        "ranges": {
            "present_mask": 31, "valid_mask": 31,
            "mm": [45, 45, 45, 45, 300], "age_ms": [3] * 5,
        },
        "imu": {
            "family": 4, "gyro_id": 104, "aux_id": 0,
            "valid": True, "acc": [0, 0, 16384], "gyro": [0, 0, 0],
            "age_ms": 10, "boot_id": 7, "sample_ms": 102,
            "low_g_valid": True, "low_g_irq": False, "low_g_seq": 0,
        },
    }


def test_actual_local_latch_is_observable_not_falsely_reported_off():
    result = inspect(status("imu_attitude_latched"))
    assert result["imu"]["attitude_interlock_active"] is True
    assert result["imu"]["attitude_local_fault"] == "imu_attitude_latched"
    assert result["imu"]["physical_qualification_pass"] is False
    assert result["local_guard_fault"] == "imu_attitude_latched"


@pytest.mark.parametrize("fault", [
    "none", "battery_low_latched", "imu_attitude_unqualified",
    "imu_attitude_not_upright", None,
])
def test_other_local_faults_do_not_prove_attitude_guard_is_disabled(fault):
    result = inspect(status(fault))
    assert result["imu"]["attitude_interlock_active"] is None
    assert result["imu"]["attitude_local_fault"] == (
        fault if fault in ("imu_attitude_unqualified", "imu_attitude_not_upright")
        else None
    )
    assert result["imu"]["physical_qualification_pass"] is False


@pytest.mark.parametrize("fault", [True, 1, [], {}, "F" * 81])
def test_malformed_or_unbounded_fault_provenance_is_rejected(fault):
    with pytest.raises(ValueError, match="local fault identity"):
        inspect(status(fault))
