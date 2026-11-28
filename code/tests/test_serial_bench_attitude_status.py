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


def status_with_optional_inputs():
    data = status()
    data["extras"] = {
        "mask": 7, "bumper": False, "reed": False, "pir": False,
        "bumps": 0, "reed_count": 0, "pir_count": 0,
        "cap": 3, "cap_ok": True, "cap_events": 7,
    }
    data["side_ranges"] = {
        "present_mask": 7, "valid_mask": 5, "mm": [120, 0, 1300],
        "age_ms": [0, 200, 201], "motion_certified": False,
    }
    return data


def test_optional_inputs_preserve_read_only_provenance():
    result = inspect(status_with_optional_inputs())
    assert result["cap_touch"] == {
        "reported": True, "valid": True, "zone_mask": 3,
        "rising_zone_events": 7, "physical_qualification_pass": False,
    }
    assert result["side_ranges"]["readings"] == [
        {"direction": "left", "distance_mm": 120, "age_ms": 0,
         "present": True, "valid": True},
        {"direction": "right", "distance_mm": 0, "age_ms": 200,
         "present": True, "valid": False},
        {"direction": "rear", "distance_mm": 1300, "age_ms": 201,
         "present": True, "valid": True},
    ]
    assert result["side_ranges"]["motion_certified"] is False
    assert result["eligible_for_manual_local_rearm"] is True
    assert result["physical_qualification_pass"] is False


@pytest.mark.parametrize("backend, age, distance, bumper, eligible", [
    ("stepper_28byj48", 199, 1, False, True),
    ("stepper_28byj48", 200, 1, False, False),
    ("stepper_28byj48", 199, 0, False, False),
    ("stepper_28byj48", 199, 1300, True, False),
    ("dc_pwm_guarded", 199, 1300, False, False),
])
def test_manual_rearm_eligibility_boundaries(backend, age, distance, bumper, eligible):
    data = status_with_optional_inputs()
    data["backend"] = backend
    data["ranges"]["age_ms"][0] = age
    data["ranges"]["mm"][0] = distance
    data["extras"]["bumper"] = bumper
    assert inspect(data)["eligible_for_manual_local_rearm"] is eligible


@pytest.mark.parametrize("section, key, value, message", [
    ("ranges", "mm", [True] * 5, "Malformed or out-of-range WROOM status"),
    ("imu", "boot_id", 0, "Malformed IMU boot/acquisition source identity"),
    ("imu", "age_ms", 201, "Malformed or stale IMU six-axis diagnostics"),
    ("extras", "mask", True, "Invalid optional sensor enable mask"),
    ("extras", "cap_ok", False, "Invalid CAP1188 touch source or zone mask"),
    ("side_ranges", "mm", [0, 0, 1300], "Invalid read-only side and rear ToF data"),
    ("side_ranges", "motion_certified", 0, "Invalid read-only side and rear ToF data"),
])
def test_phase_validation_preserves_exact_errors(section, key, value, message):
    data = status_with_optional_inputs()
    data[section][key] = value
    with pytest.raises(ValueError) as error:
        inspect(data)
    assert str(error.value) == message


def test_optional_validation_precedes_native_low_g_validation():
    data = status_with_optional_inputs()
    del data["imu"]["low_g_seq"]
    del data["extras"]["cap_events"]
    data["side_ranges"]["motion_certified"] = True
    for message in ("Incomplete CAP1188 optional telemetry",
                    "Invalid read-only side and rear ToF data",
                    "Incomplete MPU6050 free-fall interrupt telemetry"):
        with pytest.raises(ValueError) as error:
            inspect(data)
        assert str(error.value) == message
        if message.startswith("Incomplete CAP1188"):
            data["extras"]["cap_events"] = 7
        else:
            data["side_ranges"]["motion_certified"] = False
