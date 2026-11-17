"""Source-only contract for the printable one-robot signal harness.

A green result NEVER qualifies a battery, safe contact or physical harness.
"""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "desk_robot_harness", ROOT / "code/scripts/emit_wiring_manifest.py"
)
harness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(harness)


def sources():
    return (
        json.loads((ROOT / harness.PLAN).read_text()),
        (ROOT / harness.BODY_PINS).read_text(),
        (ROOT / harness.HEAD_PINS).read_text(),
    )


def test_full_wroom_xiao_signal_harness_matches_real_firmware():
    plan, body, sense = sources()
    page = harness.render(plan, body, sense)
    assert page.startswith("# One robot: firmware checked SIGNAL harness")
    assert "| WROOM GPIO13 | left ULN2003 IN1 |" in page
    assert "| WROOM GPIO23 | right ULN2003 IN4 |" in page
    assert "| WROOM GPIO25 + GPIO26 | left DRV8833 AIN1/AIN2 (DC FULL only) |" in page
    assert "| WROOM GPIO27 + GPIO32 | right DRV8833 BIN1/BIN2 (DC FULL only) |" in page
    assert "Motor variants are mutually exclusive" in page
    assert "| XIAO GPIO2 TX | WROOM GPIO16 RX |" in page
    assert "| WROOM GPIO17 TX | XIAO GPIO1 RX |" in page
    assert "| WROOM GPIO18 | MG90S lift signal |" in page
    assert "| WROOM GPIO19 | MG90S jaw signal |" in page
    assert "| XIAO GPIO4 | MAX98357A BCLK |" in page
    assert "| WROOM GPIO34 | AT42QT1010 OUT |" in page
    assert page.count("Range TCA9548A 0x70 CH") == 8
    assert page.count("Accessory TCA9548A 0x71 CH") == 8
    assert "PN532 I2C (0x24)" in page
    assert "MCP23017 (0x20)" in page
    assert "| MCP23017 GPB0 | optional reed switch |" in page
    assert "| MCP23017 GPB1 | optional PIR output |" in page
    assert "| WROOM GPIO36 reserved | left 38kHz IR demodulator |" in page
    assert "| WROOM GPIO39 reserved | right 38kHz IR demodulator |" in page
    assert "VL53L0X (0x29)" in page
    # All eight Pololu-style carrier lanes are UNPOWERED until actual
    # VIN and pullup levels are measured, not merely firmware allocated.
    assert page.count(
        "Unqualified carrier; DO NOT ENERGIZE before voltage checks"
    ) == 8
    assert page.count("SDA/SCL pullup voltage UNKNOWN; 5V exposure forbidden") == 8
    assert "All eight VL53L0X carriers: identify PCB revision" in page
    assert "Do NOT energize any ToF lane until 5V WROOM exposure is excluded" in page
    assert "Assembly readiness: NO" in page
    assert "Do NOT wire yet" in page
    assert "NEVER directly tie robot boost 5V to laptop USB VBUS" in page
    assert "continuity-checked before GPIO7/8 I2S and GPIO9 RGB use" in page
    # The checked-in assembly sheet is generated, never a second manual map.
    assert (ROOT / "docs/hardware/one-robot-signal-harness.generated.md").read_text() == page


def test_actual_pin_reassignment_fails_before_releasing_harness():
    plan, body, sense = sources()
    wrong = copy.deepcopy(plan)
    wrong["bus"]["sense_gpio"]["head_uart_rx"] = 12
    with pytest.raises(ValueError, match="pin drift"):
        harness.verify(wrong, body, sense)
    wrong = copy.deepcopy(plan)
    wrong["bus"]["body_gpio"]["left_stepper"][0] = 4
    with pytest.raises(ValueError, match="Stepper phase pin drift"):
        harness.verify(wrong, body, sense)
    with pytest.raises(ValueError, match="Guarded DC motor pin drift"):
        harness.verify(plan, body.replace("constexpr int kLeftIn1 = 25;",
                                          "constexpr int kLeftIn1 = 4;"), sense)
    with pytest.raises(ValueError, match="Missing or duplicate"):
        harness.verify(plan, body, sense.replace(
            "#define ROBOT_UART_RX GPIO_NUM_1", ""
        ))


def test_unqualified_bus_edits_cannot_silently_change_critical_floor():
    plan, body, sense = sources()
    bad = copy.deepcopy(plan)
    bad["bus"]["mux_ranges"]["channels"][0]["position"] = "rear_obstacle"
    with pytest.raises(ValueError, match="Critical cliff"):
        harness.verify(bad, body, sense)
    # The former check only covered lanes 0 and 4. A swapped rear cliff
    # sensor could otherwise produce a plausible but dangerously wrong map.
    for first, second in ((1, 2), (2, 3), (5, 6), (6, 7)):
        bad = copy.deepcopy(plan)
        lanes = bad["bus"]["mux_ranges"]["channels"]
        lanes[first]["position"], lanes[second]["position"] = (
            lanes[second]["position"], lanes[first]["position"]
        )
        with pytest.raises(ValueError, match="Critical cliff/obstacle"):
            harness.verify(bad, body, sense)
    bad = copy.deepcopy(plan)
    bad["bus"]["mux_extras"]["channels"][5]["devices"].append(
        {"name": "same I2C address", "address": 0x24}
    )
    with pytest.raises(ValueError, match="Duplicate mux_extras"):
        harness.verify(bad, body, sense)
    bad = copy.deepcopy(plan)
    bad["bus"]["body_gpio"]["terminal_ir_right_reserved"] = (
        bad["bus"]["body_gpio"]["terminal_ir_left_reserved"]
    )
    with pytest.raises(ValueError, match="Double-booked"):
        harness.verify(bad, body, sense)
