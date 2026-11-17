"""Official Seeed and real working XIAO desk robot supply path contract.

The diode/bulk components are part of the existing per-robot switch_power
kit, not duplicate cart rows. These source-level tests cannot establish
unpowered backfeed current or servo startup brownout margins.
"""
import json
from pathlib import Path

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
