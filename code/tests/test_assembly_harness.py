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
    assert "CAP1188 (0x29), MAX30102 paw pad (0x57)" in page
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


@pytest.mark.parametrize("bad_gpio", [6, 12, 42])
def test_selected_wroom_actuator_pin_cannot_be_flash_boot_or_xiao_only(bad_gpio):
    plan, body, sense = sources()
    bad = copy.deepcopy(plan)
    bad["bus"]["body_gpio"]["lift_servo"] = bad_gpio
    modified = body.replace(
        "constexpr int kLiftServo = 18;",
        f"constexpr int kLiftServo = {bad_gpio};",
    )
    assert modified != body
    # Even a matching firmware + plan edit is not proof that the module has
    # this output pad or that driving it is safe for the selected boot path.
    with pytest.raises(ValueError, match="WROOM32"):
        harness.verify(bad, modified, sense)


def test_wroom_input_only_pad_cannot_be_reassigned_to_servo_output():
    plan, body, sense = sources()
    bad = copy.deepcopy(plan)
    # Exchange the input touch sensor and servo to avoid triggering the
    # duplicate-pin guard first. The firmware and plan now agree exactly.
    bad["bus"]["body_gpio"]["lift_servo"] = 34
    bad["bus"]["body_gpio"]["head_touch"] = 18
    modified = body.replace(
        "constexpr int kLiftServo = 18;", "constexpr int kLiftServo = 34;"
    ).replace(
        "constexpr int kTouchOutput = 34;", "constexpr int kTouchOutput = 18;"
    )
    assert modified != body
    with pytest.raises(ValueError, match="WROOM32 output GPIO"):
        harness.verify(bad, modified, sense)


def test_wroom_sensor_input_cannot_use_unbonded_xiao_gpio():
    plan, body, sense = sources()
    bad = copy.deepcopy(plan)
    bad["bus"]["body_gpio"]["head_touch"] = 42
    modified = body.replace(
        "constexpr int kTouchOutput = 34;", "constexpr int kTouchOutput = 42;"
    )
    assert modified != body
    with pytest.raises(ValueError, match="WROOM32 GPIO"):
        harness.verify(bad, modified, sense)


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


def test_nc_bumper_wiring_instructions_match_firmware_trip_polarity():
    """An assembler must not invert a fail-closed GPIO35 safety input."""
    main = (ROOT / "code/firmware/body/src/main.cpp").read_text()
    wiring = (ROOT / "docs/hardware/wiring.md").read_text()
    row = next(line for line in wiring.splitlines()
               if line.startswith("| GPIO35, build flag DESK_ROBOT_ENABLE_BUMPER |"))
    assert "digitalRead(body_pins::kBumperInput) == HIGH" in main
    assert "NC series to GND; open or unplugged -> HIGH trip" in main
    assert "normally closed contacts hold GPIO35 LOW" in row
    assert "active HIGH trip" in row
    assert "active LOW;" not in row


def test_selected_vl53l0x_is_not_mislabelled_as_historical_only():
    definition = (ROOT / "docs/product-definition.md").read_text()
    bus = (ROOT / "code/firmware/body/lib/TofBus/TofBus.cpp").read_text()
    assert "#include <VL53L0X.h>" in (
        ROOT / "code/firmware/body/lib/TofBus/TofBus.h"
    ).read_text()
    assert "VL53L0X uses a single-byte register address" in bus
    assert "The selected VL53L0X source still requires exact carrier and optical qualification." in definition
    assert "historical VL53L0X options" not in definition


def test_max30102_wiring_assignment_is_not_speculative():
    """Pin the accepted accessory lane; code must not route it to Sense PDM."""
    definition = (ROOT / "docs/product-definition.md").read_text()
    wiring = (ROOT / "docs/hardware/wiring.md").read_text()
    assert "MAX30102 belongs on the **WROOM body** I2C" in definition
    assert "accessory mux `0x71` channel 0 at address `0x57`" in definition
    assert "potentially an unused mux channel" not in definition
    assert "CH0 CAP1188 0x29 default / 0x28 strapped + MAX30102 0x57" in wiring


def test_current_builder_guide_keeps_selected_sense_and_motor_profiles():
    """Builder instructions must not silently return to the obsolete 2026-11-03 image."""
    source = (ROOT / "code/firmware/body/platformio.ini").read_text()
    builder = (ROOT / "docs/guides/build.md").read_text(encoding="utf-8")
    head_script = (ROOT / "code/scripts/build_head.sh").read_text()
    assert "default_envs = esp32_full" in source
    assert "[env:esp32_dc_full]" in source
    assert "sense) variant=desk-robot-sense-s3" in head_script
    assert "defaults to `esp32_full`" in builder
    assert "`-e esp32_dc_full`" in builder
    assert "bash scripts/build_head.sh --board sense" in builder
    assert "--board sense --upstream upstream/xiaozhi-esp32" in builder
    assert "motor-power cutoff **unqualified and disabled**" in builder
    assert "historical Freenove modular and CoreS3 sections" in builder
    assert "default build is now `esp32_stepper`" not in builder
    assert "It has no ToF I/O/calibration supplied" not in builder
    assert builder.startswith("# One robot build and firmware guide")
    assert "## Complete first robot route" in builder
    for path in (
        "../hardware/one-robot-inventory-and-shopping.md",
        "../cad/FUSION_MEASUREMENT_SHEET.md",
        "../cad/remixes/one_robot_adapter_kit_README.md",
        "../cad/FUSION_ONE_ROBOT_ASSEMBLY.md",
        "../hardware/one-robot-signal-harness.generated.md",
        "../hardware/wiring.md",
        "../hardware/one-robot-power-gate.md",
        "imu-handling.md",
        "jaw-calibration-helper.md",
        "first-gripper-test.md",
        "../records/verification.md",
    ):
        assert path in builder
    assert "A1 through A12" in builder
    assert "Release the final print set only after qualification" in builder
