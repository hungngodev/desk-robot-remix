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
    assert "VL53L4CD (0x29)" in page
    assert "Assembly readiness: NO" in page
    assert "Do NOT wire yet" in page


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
    bad = copy.deepcopy(plan)
    bad["bus"]["mux_extras"]["channels"][5]["devices"].append(
        {"name": "same I2C address", "address": 0x24}
    )
    with pytest.raises(ValueError, match="Duplicate mux_extras"):
        harness.verify(bad, body, sense)
    bad = copy.deepcopy(plan)
    bad["bus"]["body_gpio"]["pir"] = bad["bus"]["body_gpio"]["reed"]
    with pytest.raises(ValueError, match="Double-booked"):
        harness.verify(bad, body, sense)
