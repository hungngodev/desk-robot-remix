"""Keep Stage 7 accessory evidence distinct from physical acceptance."""
from pathlib import Path

import pytest

PLAN = Path(__file__).resolve().parents[2] / "docs/PLAN.md"


def _assert_accessory_hold(plan):
    stage = plan.split(
        "## Stage 7: full local pet expressions and physical interactions\n", 1,
    )[1]
    stage = stage.split("\n## ", 1)[0]
    assert "Their hardware must be individually qualified" in stage
    assert "**0x71 accessory evidence:**" in stage
    assert "software regression coverage; physical bench pending" in stage
    assert "exact-commit CI" in stage
    for part in (
        "CAP1188", "MAX30102", "APDS9960", "AS5600", "ADS1115/FSR",
        "SHT41", "BMP280", "INA226", "MAX17048", "PN532",
    ):
        assert part in stage
    assert "`valid` is sample validity, not physical qualification" in stage
    assert "MCP23017 dock interlock remains required" in stage
    assert "eight `0x70` VL53L0X channels" in stage
    assert "physical HOLD" in stage


def test_stage_seven_keeps_accessory_qualification_pending():
    _assert_accessory_hold(PLAN.read_text(encoding="utf-8"))


@pytest.mark.parametrize(("original", "replacement"), [
    ("physical bench pending", "physical bench passed"),
    ("software regression coverage", "physical acceptance"),
    (
        "Their hardware must be individually qualified",
        "Their hardware remains individually qualified",
    ),
    ("MCP23017 dock interlock remains required", "MCP23017 dock interlock is optional"),
    (
        "`valid` is sample validity, not physical qualification",
        "`valid` proves physical qualification",
    ),
])
def test_accessory_hold_rejects_status_drift(original, replacement):
    plan = PLAN.read_text(encoding="utf-8")
    assert original in plan
    with pytest.raises(AssertionError):
        _assert_accessory_hold(plan.replace(original, replacement, 1))
