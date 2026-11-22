"""Physical purchasing signoff rejects impossible negative safety metrics.

Pure receipt structure checks only. Real instrument and mounted-hardware
qualification are still mandatory for release.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "code/scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location(
    "procurement_gate_signoff", SCRIPTS / "verify_procurement_receipts.py"
)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def physical_reading(gate, *, value, minimum, maximum):
    name, unit = release.PHYSICAL_GATE_METRICS[gate]
    conditions = {
        "setup": "identified mounted test fixture",
        "instrument": "calibrated measuring instrument",
    }
    if gate == "hardware_motor_driver_fails_low_after_cpu_stall":
        # A structurally valid cutoff time still needs independent physical
        # fault injection and timestamped oscilloscope/logic analyzer proof.
        conditions.update({
            "instrument": "calibrated logic analyzer",
            "instrument_type": "logic_analyzer",
            "fault_injection": "cpu_stall",
        })
    return {
        "sample_count": 3,
        "conditions": conditions,
        "quantities": [{
            "name": name, "unit": unit,
            "value": value, "minimum": minimum, "maximum": maximum,
        }],
    }


@pytest.mark.parametrize("gate", sorted(release.NONNEGATIVE_PHYSICAL_GATES))
@pytest.mark.parametrize(("value", "minimum", "maximum"), [
    (-2, -3, 10),
    (5, -1, 10),
    (-2, -3, -1),
])
def test_critical_nonnegative_quantity_and_bounds_cannot_be_negative(
    gate, value, minimum, maximum,
):
    observation = physical_reading(
        gate, value=value, minimum=minimum, maximum=maximum,
    )
    assert not release._qualified_gate_measurement(gate, observation)


@pytest.mark.parametrize("gate", sorted(release.NONNEGATIVE_PHYSICAL_GATES))
def test_nonnegative_critical_quantity_at_zero_or_positive_value(gate):
    for value in (0, 5, 10):
        observation = physical_reading(
            gate, value=value, minimum=0, maximum=10,
        )
        assert release._qualified_gate_measurement(gate, observation)


@pytest.mark.parametrize("gate", [
    "protected_1s_charger_and_dock_contacts",
    "amplifier_speaker_power_limit_and_thermal_trial",
])
def test_signed_pack_current_and_celsius_observation_remain_possible(gate):
    observation = physical_reading(
        gate, value=-2, minimum=-10, maximum=5,
    )
    assert release._qualified_gate_measurement(gate, observation)


def test_signoff_validation_also_applies_to_scoped_immutable_records():
    gate = "hardware_motor_driver_fails_low_after_cpu_stall"
    observed = physical_reading(
        gate, value=-2, minimum=-3, maximum=0,
    )
    assert not release._qualified_gate_measurement(gate, observed)
