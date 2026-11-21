"""Protect the selected VL53L0X hardware from stale legacy buying guidance.

Source consistency is not proof of carrier voltages or range calibration.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_current_range_selection_matches_driver_and_documents():
    driver = (ROOT / "code/firmware/body/lib/TofBus/TofBus.h").read_text()
    ini = (ROOT / "code/firmware/body/platformio.ini").read_text()
    original = (ROOT / "docs/research/2026-11-10-original-html-link-and-hardware-audit.md").read_text()
    reuse = (ROOT / "docs/research/2026-11-10-active-open-source-reuse-pass.md").read_text()
    verification = (ROOT / "docs/records/verification.md").read_text()
    historical = (ROOT / "docs/research/2026-11-13-vl53l4cd-carrier-logic-level-gate.md").read_text()
    assert "#include <VL53L0X.h>" in driver
    assert "kRangeCount = 5 + (DESK_ROBOT_EXTRA_RANGERS ? 3 : 0)" in driver
    assert "vl53l0x-arduino.git#1.3.1" in ini
    assert "-DDESK_ROBOT_EXTRA_RANGERS=1" in ini
    assert "eight generic VL53L0X channels" in original
    assert "Pololu VL53L0X Arduino library" in reuse
    assert "all eight selected VL53L0X lanes" in verification
    assert "Pololu VL53L0X and OzzMaker" in verification
    for text in (original, reuse, verification):
        assert "selected VL53L4CD" not in text
        assert "Five core VL53L4CD" not in text
    assert "SUPERSEDED HARDWARE SELECTION" in historical
    assert "DO NOT USE THIS DOCUMENT AS CURRENT GY-530 WIRING" in historical
    assert "Pololu #3692" in historical


def test_hardware_selection_does_not_authorize_real_motion():
    ini = (ROOT / "code/firmware/body/platformio.ini").read_text()
    assert "-DDESK_ROBOT_STEPPER_HARDWARE_CUTOFF_QUALIFIED=0" in ini
    assert "Three side/rear readings are diagnostics" in ini
