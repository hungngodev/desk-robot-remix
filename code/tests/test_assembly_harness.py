"""Source-only contract for the printable one-robot signal harness.

A green result NEVER qualifies a battery, safe contact or physical harness.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
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
        harness.read_wiring_plan(ROOT / harness.PLAN),
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
    assert "| AT42QT1010 OUT | WROOM GPIO34 |" in page
    assert "| 3.3V external pullup node + NC bumper switch series -> GND | WROOM GPIO35 |" in page
    assert "NC bumper series OUT" not in page
    assert page.count("Range TCA9548A 0x70 CH") == 8
    assert page.count("Accessory TCA9548A 0x71 CH") == 8
    assert "PN532 I2C (0x24)" in page
    assert "MCP23017 (0x20)" in page
    assert "| Optional reed switch to GND (with external 3.3V pullup) | MCP23017 GPB0 |" in page
    assert "| Optional PIR output | MCP23017 GPB1 |" in page
    assert "| left 38kHz IR demodulator | WROOM GPIO36 reserved |" in page
    assert "| right 38kHz IR demodulator | WROOM GPIO39 reserved |" in page
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

def test_strict_wiring_plan_preserves_current_source_mapping():
    path = ROOT / harness.PLAN
    assert harness.read_wiring_plan(path) == json.loads(
        path.read_text(encoding="utf-8")
    )
    _, body, sense = sources()
    assert harness.render(harness.read_wiring_plan(path), body, sense) == (
        ROOT / "docs/hardware/one-robot-signal-harness.generated.md"
    ).read_text()


@pytest.mark.parametrize("before,after", [
    ('"sda": 21', '"sda": 6, "sda": 21'),
    ('"position": "floor_front_left"',
     '"position": "wrong_cliff", "position": "floor_front_left"'),
    ('"schema_version": 1', '"schema_version": 99, "schema_version": 1'),
    ('"bus": {', '"bus": {}, "bus": {'),
])
def test_ambiguous_json_cannot_hide_conflicting_wiring_or_cliff_plan(
    tmp_path, before, after,
):
    source = (ROOT / harness.PLAN).read_text(encoding="utf-8")
    assert source.count(before) == 1
    forged = source.replace(before, after)
    path = tmp_path / "ambiguous_full_feature_plan.json"
    path.write_text(forged, encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate wiring plan JSON field"):
        harness.read_wiring_plan(path)


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_nonstandard_json_number_never_reaches_wiring_release(tmp_path, token):
    source = (ROOT / harness.PLAN).read_text(encoding="utf-8")
    assert source.count('"sda": 21') == 1
    path = tmp_path / "bad_numeric_wiring_plan.json"
    path.write_text(source.replace('"sda": 21', f'"sda": {token}'))
    with pytest.raises(ValueError, match="Nonfinite wiring plan JSON constant"):
        harness.read_wiring_plan(path)


def test_wiring_manifest_cli_validates_before_replacing_output(tmp_path):
    """Run the real CLI, not a mock of the parser or render function."""
    for relative in (harness.PLAN, harness.BODY_PINS, harness.HEAD_PINS):
        dest = tmp_path / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((ROOT / relative).read_bytes())

    output = tmp_path / "harness.md"
    command = [
        sys.executable, str(ROOT / "code/scripts/emit_wiring_manifest.py"),
        "--root", str(tmp_path), "--out", str(output),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    expected = (
        ROOT / "docs/hardware/one-robot-signal-harness.generated.md"
    ).read_bytes()
    assert output.read_bytes() == expected

    plan_path = tmp_path / harness.PLAN
    source = plan_path.read_text(encoding="utf-8")
    assert source.count('"sda": 21') == 1
    plan_path.write_text(
        source.replace('"sda": 21', '"sda": 6, "sda": 21'),
        encoding="utf-8",
    )
    result = subprocess.run(command, capture_output=True, text=True, timeout=15)
    assert result.returncode != 0
    assert "Duplicate wiring plan JSON field: sda" in result.stderr
    assert output.read_bytes() == expected

    plan_path.write_text(source, encoding="utf-8")
    body_path = tmp_path / harness.BODY_PINS
    body = body_path.read_text(encoding="utf-8")
    changed = body.replace("constexpr int kLiftServo = 18;",
                           "constexpr int kLiftServo = 4;")
    assert changed != body
    body_path.write_text(changed, encoding="utf-8")
    result = subprocess.run(command, capture_output=True, text=True, timeout=15)
    assert result.returncode != 0
    assert "Firmware body pin drift: lift_servo" in result.stderr
    assert output.read_bytes() == expected


@pytest.mark.parametrize("channel", [4, 5, 6, 7])
def test_accessory_safety_device_substitution_cannot_release_harness(channel):
    plan, body, sense = sources()
    lane = next(
        lane for lane in plan["bus"]["mux_extras"]["channels"]
        if lane["channel"] == channel
    )
    lane["devices"][0]["name"] = "unreviewed substitute"
    message = (
        "Dock accessory lane 5" if channel == 5
        else f"Accessory lane {channel} battery/wheel identity drift"
    )
    with pytest.raises(ValueError, match=message):
        harness.render(plan, body, sense)


@pytest.mark.parametrize("field", [
    "module_vin_v", "tca9548a_vcc_v",
    "upstream_pullup_target_v", "downstream_pullup_target_v",
])
def test_range_power_contract_rejects_five_volt_substitution(field):
    plan, body, sense = sources()
    plan["range_breakout_power_contract"][field] = 5
    with pytest.raises(ValueError, match="GY-530 power voltage"):
        harness.render(plan, body, sense)


@pytest.mark.parametrize("field,value", [
    ("amplifier_vdd_v", True),
    ("speaker_nominal_impedance_ohm", 4),
    ("speaker_nominal_rating_w", 1),
    ("physical_release", "approved"),
])
def test_audio_contract_rejects_unreviewed_electrical_changes(field, value):
    plan, body, sense = sources()
    plan["audio_output_power_contract"][field] = value
    with pytest.raises(ValueError, match="speaker amplifier power contract"):
        harness.render(plan, body, sense)


def test_dc_heartbeat_must_stay_on_mutually_exclusive_stepper_pin():
    plan, body, sense = sources()
    changed = body.replace("constexpr int kDcHeartbeatPin = 23;",
                           "constexpr int kDcHeartbeatPin = 25;")
    assert changed != body
    with pytest.raises(ValueError, match="DC motor watchdog"):
        harness.render(plan, changed, sense)


def test_wiring_guide_reconciles_parent_roles_and_cap1188_address():
    plan = json.loads((ROOT / "docs/hardware/full-feature-plan.json").read_text())
    owners = json.loads(
        (ROOT / "docs/hardware/full-63-role-source-ownership.json").read_text()
    )
    guide = (ROOT / "docs/hardware/full-feature-wiring-and-shopping.md").read_text()
    groups = (
        (plan["parts"], owners["pet_roles"]),
        (plan["room_pod"]["modules"], owners["room_roles"]),
        (plan["linked_subassemblies"], owners["linked_roles"]),
    )
    for rows, mapping in groups:
        assert {row["id"] for row in rows} == set(mapping)
    counts = tuple(len(rows) for rows, _ in groups)
    assert counts == (42, 7, 14)
    assert "49 parent\npurchasing roles" in guide
    assert "63 records total" in guide
    assert "not another 14 purchases" in guide
    assert "full-63-role-source-ownership.json" in guide
    lane = plan["bus"]["mux_extras"]["channels"][0]
    assert {dev["name"]: dev["address"] for dev in lane["devices"]} == {
        "CAP1188": 0x29,
        "MAX30102 paw pad": 0x57,
    }
    assert "planned 0x29 (or the supported strapped 0x28 alternative)" in guide
    assert "150 kΩ ADDR_COMM pull-down" in guide
    assert "0x28 with ADDR_COMM tied to VDD" in guide


def test_wiring_guide_does_not_mix_drivetrain_variants():
    guide = (ROOT / "docs/hardware/full-feature-wiring-and-shopping.md").read_text()
    _, body, _ = sources()
    assert "Motor variants are mutually exclusive" in guide
    assert "left ULN2003 stepper (STEP only)" in guide
    assert "right ULN2003 stepper (STEP only)" in guide
    for name, gpio in (
        ("kLeftIn1", 25), ("kLeftIn2", 26),
        ("kRightIn1", 27), ("kRightIn2", 32), ("kDcHeartbeatPin", 23),
    ):
        assert f"{name} = {gpio};" in body
    assert "GPIO25/26 to DRV8833 AIN1/AIN2" in guide
    assert "GPIO27/32 to BIN1/BIN2" in guide
    assert "not a direct connection to nSLEEP" in guide
    assert "MCP23017 GPB3 on mux 0x71 channel 5" in guide
