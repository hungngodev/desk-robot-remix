"""Official Seeed and real working XIAO desk robot supply path contract.

The diode/bulk components are part of the existing per-robot switch_power
kit, not duplicate cart rows. These source-level tests cannot establish
unpowered backfeed current or servo startup brownout margins.
"""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HARDWARE = ROOT / "docs/hardware"


def test_one_per_robot_power_kit_contains_reference_proven_parts():
    plan = json.loads((HARDWARE / "full-feature-plan.json").read_text())
    kit = next(p for p in plan["parts"] if p["id"] == "switch_power")
    assert kit["per_robot"] == 1
    assert kit["reported_owned_total"] == 0
    assert "Schottky" in kit["notes"]
    assert "cathode on XIAO 5V" in kit["notes"]
    assert "470uF" in kit["notes"]
    assert "1N5817" in kit["notes"]
    assert "0.1uF plus 10uF" in kit["notes"]
    assert "NOT proof" in kit["notes"]
    # Reuse the single existing switch_power kit, not new independent BOM IDs.
    names = {p["id"] for p in plan["parts"]}
    assert "xiao_extra_diode" not in names
    assert "servo_extra_battery" not in names


def test_harness_and_generator_match_isolated_usb_and_actuator_power():
    generator = (ROOT / "code/scripts/emit_wiring_manifest.py").read_text()
    harness = (HARDWARE / "one-robot-signal-harness.generated.md").read_text()
    for marker in ("XIAO Sense 5V input at Schottky cathode",
                   "MG90S lift/grip and motor driver VM power",
                   "MAX98357A VIN with local 0.1uF + 10uF decoupling"):
        assert marker in generator
        assert marker in harness
    assert "NEVER via XIAO 3V3 or USB/diode" in harness
    assert "470uF documented in cgro00 V2 servo wiring" in harness
    assert "NOT sufficient-rating proof for this robot" in harness


def test_release_requires_real_backfeed_and_brownout_evidence():
    release = (ROOT / "code/scripts/procurement_release.py").read_text()
    assert '"xiao_usb_backfeed_diode_and_servo_brownout_trial"' in release
    checklist = (HARDWARE / "complete-shopping-checklist.md").read_text()
    assert "One rated assembly kit; no high current DuPont wires." in checklist
    assert "XIAO 5V" in checklist
    assert "470uF" in checklist
    assert "1N5817" in checklist


POWER_GATE = "xiao_usb_backfeed_diode_and_servo_brownout_trial"


@pytest.fixture
def receipt_verifier(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "code/scripts"))
    import verify_procurement_receipts

    return verify_procurement_receipts


def test_xiao_trial_is_mandatory_for_first_robot_and_fleet(receipt_verifier):
    for first_robot in (True, False):
        receipts = list(receipt_verifier.required_receipts({}, first_robot=first_robot))
        assert ("system", POWER_GATE, None) in receipts


def _synthetic_power_measurement():
    # Synthetic validator inputs only; not measured current or approved limits.
    values = (
        ("usb_attach_trials", "trials", 1, 1),
        ("usb_detach_trials", "trials", 1, 1),
        ("cold_start_trials", "trials", 1, 1),
        ("loaded_servo_start_trials", "trials", 1, 1),
        ("usb_to_boost_reverse_current_ma", "mA", 0.01, 0.1),
        ("boost_to_usb_reverse_current_ma", "mA", 0.01, 0.1),
        ("idle_head_current_ma", "mA", 40, 100),
        ("active_head_peak_current_ma", "mA", 300, 500),
        ("head_3v3_ramp_time_ms", "ms", 2, 10),
        ("head_3v3_minimum_operating_v", "V", 3.2, 3.6),
        ("head_3v3_maximum_operating_v", "V", 3.4, 3.6),
        ("head_rail_stable_before_chip_enable_us", "us", 100, 200),
        ("unexpected_head_resets", "events", 0, 0),
    )
    return {
        "sample_count": 4,
        "conditions": {
            "setup": "installed_head_power_fixture",
            "instrument": "scope_and_current_meter",
            "installed_hardware": "head_revision_A",
            "procedure_revision": "power_trial_A",
            "instrument_type": "oscilloscope_and_ammeter",
            "power_path_revision": "isolated_supply_A",
            "oscilloscope_capture_id": "synthetic_ramp_capture",
            "current_capture_id": "synthetic_current_capture",
            "head_firmware_commit": "a" * 40,
        },
        "quantities": [
            {"name": name, "unit": unit, "value": value,
             "minimum": 0, "maximum": maximum}
            for name, unit, value, maximum in values
        ],
    }


def test_xiao_receipt_requires_measurements_not_narrative(receipt_verifier):
    assert not receipt_verifier._qualified_gate_measurement(
        POWER_GATE, {"observed": "passed"}
    )
    assert receipt_verifier._qualified_gate_measurement(
        POWER_GATE, _synthetic_power_measurement()
    )


@pytest.mark.parametrize("metric", [
    "usb_attach_trials", "usb_detach_trials", "cold_start_trials",
    "loaded_servo_start_trials", "usb_to_boost_reverse_current_ma",
    "boost_to_usb_reverse_current_ma", "idle_head_current_ma",
    "active_head_peak_current_ma", "head_3v3_ramp_time_ms",
    "head_3v3_minimum_operating_v", "head_3v3_maximum_operating_v",
    "head_rail_stable_before_chip_enable_us",
    "unexpected_head_resets",
])
def test_xiao_receipt_rejects_missing_observation(receipt_verifier, metric):
    evidence = _synthetic_power_measurement()
    evidence["quantities"] = [
        item for item in evidence["quantities"] if item["name"] != metric
    ]
    assert not receipt_verifier._qualified_gate_measurement(POWER_GATE, evidence)


@pytest.mark.parametrize(("metric", "value"), [
    ("usb_attach_trials", True),
    ("usb_detach_trials", 0),
    ("usb_to_boost_reverse_current_ma", 0.2),
    ("boost_to_usb_reverse_current_ma", -0.01),
    ("idle_head_current_ma", 0),
    ("active_head_peak_current_ma", 20),
    ("active_head_peak_current_ma", float("nan")),
    ("head_3v3_ramp_time_ms", 0),
    ("head_3v3_ramp_time_ms", 11),
    ("head_3v3_minimum_operating_v", 2.99),
    ("head_3v3_minimum_operating_v", 3.5),
    ("head_3v3_maximum_operating_v", 3.1),
    ("head_3v3_maximum_operating_v", 3.61),
    ("head_rail_stable_before_chip_enable_us", 49),
    ("unexpected_head_resets", 1),
])
def test_xiao_receipt_rejects_failed_observation(receipt_verifier, metric, value):
    evidence = _synthetic_power_measurement()
    next(item for item in evidence["quantities"] if item["name"] == metric)["value"] = value
    assert not receipt_verifier._qualified_gate_measurement(POWER_GATE, evidence)


@pytest.mark.parametrize("key", [
    "power_path_revision", "oscilloscope_capture_id",
    "current_capture_id", "head_firmware_commit", "instrument_type",
])
def test_xiao_receipt_requires_instrument_capture_provenance(receipt_verifier, key):
    evidence = _synthetic_power_measurement()
    del evidence["conditions"][key]
    assert not receipt_verifier._qualified_gate_measurement(POWER_GATE, evidence)


@pytest.mark.parametrize("sample_count", [True, 0, 3])
def test_xiao_receipt_rejects_insufficient_trial_count(receipt_verifier, sample_count):
    evidence = _synthetic_power_measurement()
    evidence["sample_count"] = sample_count
    assert not receipt_verifier._qualified_gate_measurement(POWER_GATE, evidence)


def test_xiao_receipt_rejects_overstated_phase_count(receipt_verifier):
    evidence = _synthetic_power_measurement()
    evidence["quantities"][0].update(value=2, maximum=2)
    assert not receipt_verifier._qualified_gate_measurement(POWER_GATE, evidence)


def test_xiao_receipt_rejects_unpinned_firmware_revision(receipt_verifier):
    evidence = _synthetic_power_measurement()
    evidence["conditions"]["head_firmware_commit"] = "latest"
    assert not receipt_verifier._qualified_gate_measurement(POWER_GATE, evidence)


def test_xiao_receipt_rejects_duplicate_quantity(receipt_verifier):
    evidence = _synthetic_power_measurement()
    evidence["quantities"].append(evidence["quantities"][0].copy())
    assert not receipt_verifier._qualified_gate_measurement(POWER_GATE, evidence)
