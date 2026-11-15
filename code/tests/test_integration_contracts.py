"""Cross-layer contracts prevent accidental sensor and harness drift.

These are source assertions, never electrical, acoustic or safety acceptance.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from desk_robot.config import Settings, load_settings
from desk_robot.multimodal import TRIGGERS
from desk_robot.pet import (
    _DIRECT_INTERACTION_KINDS, _PHYSICAL_INITIATIVE_KINDS,
    _SOCIAL_EVENT_KINDS, _VISUAL_INITIATIVE_MIN_CONFIDENCE,
)

ROOT = Path(__file__).resolve().parents[2]
PLAN = json.loads((ROOT / "docs/hardware/full-feature-plan.json").read_text())


def test_all_firmware_sensor_reactions_have_a_real_camera_priority_label():
    # Every event produced by physical input and eligible to initiate speech
    # must be representable as a separate authenticated camera context hint.
    assert _PHYSICAL_INITIATIVE_KINDS <= TRIGGERS
    assert _DIRECT_INTERACTION_KINDS <= _PHYSICAL_INITIATIVE_KINDS
    assert _SOCIAL_EVENT_KINDS <= (
        _PHYSICAL_INITIATIVE_KINDS | _VISUAL_INITIATIVE_MIN_CONFIDENCE.keys()
    )
    assert "safety_fault" in TRIGGERS
    assert "safety_fault" not in _SOCIAL_EVENT_KINDS
    assert "battery_low" not in _SOCIAL_EVENT_KINDS


def test_real_robot_pin_allocations_do_not_double_book_same_gpio():
    bus = PLAN["bus"]
    for key in ("body_gpio", "sense_gpio"):
        pins = [
            pin for value in bus[key].values()
            for pin in (value if isinstance(value, list) else [value])
        ]
        assert pins and all(type(pin) is int and 0 <= pin <= 48 for pin in pins)
        assert len(set(pins)) == len(pins), f"Conflicting {key} GPIO allocation"
    assert bus["body_gpio"]["head_touch"] == 34
    assert bus["body_gpio"]["bumper_nc_series"] == 35
    assert bus["body_gpio"]["sda"] == 21
    assert bus["body_gpio"]["scl"] == 22
    assert bus["sense_gpio"]["amp_bclk"] == 4
    # The XIAO Sense SD J3 wire isolation is a physical task, not a pin test.
    assert not PLAN["qualified_assumptions"]


def test_current_body_and_sense_firmware_gpio_match_machine_readable_harness():
    # Source-level regression only. It cannot measure the actual board rev,
    # isolation of the XIAO Sense SD J3, polarity, or safe electrical loads.
    body = (ROOT / "code/firmware/body/include/BodyPins.h").read_text()
    sense = (ROOT / "code/firmware/head/sense/config.h").read_text()
    planned_body = PLAN["bus"]["body_gpio"]
    body_names = {
        "lift_servo": "kLiftServo", "grip_servo": "kGripServo",
        "head_uart_rx": "kUartRx", "head_uart_tx": "kUartTx",
        "sda": "kSensorSda", "scl": "kSensorScl",
        "head_touch": "kTouchOutput",
        "bumper_nc_series": "kBumperInput",
        "terminal_ir_left_reserved": "kTerminalIrLeftInput",
        "terminal_ir_right_reserved": "kTerminalIrRightInput",
    }
    for key, symbol in body_names.items():
        match = re.search(rf"constexpr int {symbol} = (\d+);", body)
        assert match is not None, f"Missing exact firmware pin {symbol}"
        assert int(match.group(1)) == planned_body[key], key

    for key, symbol in (
        ("left_stepper", "kLeftStepperPins"),
        ("right_stepper", "kRightStepperPins"),
    ):
        match = re.search(
            rf"constexpr int {symbol}\[\] = \{{([0-9, ]+)\}};", body
        )
        assert match is not None
        assert [int(pin.strip()) for pin in match.group(1).split(",")] == planned_body[key]
    assert "constexpr int kMuxReset = -1;" in body  # avoid boot strap GPIO4

    sense_names = {
        "oled_sda": "DISPLAY_SDA_PIN", "oled_scl": "DISPLAY_SCL_PIN",
        "amp_bclk": "AUDIO_I2S_SPK_GPIO_BCLK",
        "amp_lrclk": "AUDIO_I2S_SPK_GPIO_LRCK",
        "amp_din": "AUDIO_I2S_SPK_GPIO_DOUT",
        "head_uart_tx": "ROBOT_UART_TX", "head_uart_rx": "ROBOT_UART_RX",
    }
    for key, symbol in sense_names.items():
        match = re.search(rf"#define {symbol} GPIO_NUM_(\d+)\b", sense)
        assert match is not None, f"Missing Sense firmware pin {symbol}"
        assert int(match.group(1)) == PLAN["bus"]["sense_gpio"][key], key
    assert "#define AUDIO_PDM_MIC_GPIO_SCK GPIO_NUM_42" in sense
    assert "#define AUDIO_PDM_MIC_GPIO_DIN GPIO_NUM_41" in sense
    assert PLAN["bus"]["sense_gpio"]["rgb_data"] == 9
    # RGB is allocated, not automatically wired or implemented on hardware.
    assert "GPIO_NUM_9" not in sense



def test_slow_reed_pir_are_on_expander_not_the_ir_direct_input_pins():
    # Static contracts for the physical pin budget. No manufactured IR
    # receiver, valid NEC decoder or charger is implied by this source test.
    accessory = (ROOT / "code/firmware/body/lib/AccessorySensors/AccessorySensors.cpp").read_text()
    main = (ROOT / "code/firmware/body/src/main.cpp").read_text()
    body = (ROOT / "code/firmware/body/include/BodyPins.h").read_text()
    bus = PLAN["bus"]
    assert bus["body_gpio"]["terminal_ir_left_reserved"] == 36
    assert bus["body_gpio"]["terminal_ir_right_reserved"] == 39
    assert "kTerminalIrLeftInput = 36;" in body
    assert "kTerminalIrRightInput = 39;" in body
    assert "kReedInput" not in body and "kPirInput" not in body
    assert "write8(0x20, 0x01, 0xFF)" in accessory
    assert "write8(0x20, 0x0D, 0x01)" in accessory
    assert "read(0x20, 0x13, &bits, 1)" in accessory
    assert "data_.optional_inputs.valid = false;" in accessory
    assert "const auto& extension = accessories.readings().optional_inputs;" in main
    assert "now_ms - extension.at_ms <= 250U" in main
    assert "digitalRead(body_pins::kTerminalIrLeftInput)" not in main
    assert "digitalRead(body_pins::kTerminalIrRightInput)" not in main
    assert bus["mcp23017_optional_inputs"]["physical_qualified"] is False

def test_parts_inventory_does_not_conflict_with_reserved_ir_and_required_dock_io():
    """Even prose inventory hints must agree with actual WROOM and MCP pins."""
    by_id = {part["id"]: part for part in PLAN["parts"]}
    reed = by_id["reed"]["notes"]
    pir = by_id["pir"]["notes"]
    expander = by_id["mcp23017"]["notes"]
    assert "MCP23017 GPIOB0" in reed
    assert "MCP23017 GPIOB1" in pir
    assert "GPIO36 is reserved" in reed
    assert "GPIO39 is reserved" in pir
    assert "GPIOA dock" in expander
    assert "fail-closed WROOM motion interlock" in expander
    bus = PLAN["bus"]
    assert bus["mcp23017_optional_inputs"]["required_dock_gpioa_is_separate"]
    assert bus["body_gpio"]["terminal_ir_left_reserved"] == 36
    assert bus["body_gpio"]["terminal_ir_right_reserved"] == 39


def test_nec_telemetry_uses_exact_existing_wroom_xiao_mac_owners():
    body = (ROOT / "code/firmware/body/lib/BodyControl/BodyControl.cpp").read_text()
    main = (ROOT / "code/firmware/body/src/main.cpp").read_text()
    rmt = (ROOT / "code/firmware/body/lib/TerminalIr/TerminalIr.cpp").read_text()
    protocol = (ROOT / "code/firmware/head/overlay/robot_protocol.h").read_text()
    bridge = (ROOT / "code/firmware/head/overlay/robot_bridge.cc").read_text()
    transport = (ROOT / "code/laptop/src/desk_robot/transport.py").read_text()
    api = (ROOT / "code/laptop/src/desk_robot/api.py").read_text()
    profile = (ROOT / "code/firmware/body/platformio.ini").read_text()

    assert 'const bool ir = std::strcmp(command, "ir") == 0;' in body
    assert 'e.same_code ? "true" : "false"' in body
    assert 'set_terminal_ir(terminal_ir.evidence(millis()))' in main
    assert 'DESK_ROBOT_ENABLE_TERMINAL_IR' in main
    full = profile.split("[env:esp32_full]", 1)[1].split("[env:esp32_stepper]", 1)[0]
    stage = profile.split("[env:esp32_stepper]", 1)[1]
    assert "-DDESK_ROBOT_ENABLE_TERMINAL_IR=1" in full
    assert "-DDESK_ROBOT_ENABLE_TERMINAL_IR=1" not in stage
    assert "RMT_CHANNEL_0" in (
        ROOT / "code/firmware/body/lib/TerminalIr/TerminalIr.h"
    ).read_text()
    assert "RMT_CHANNEL_1" in (
        ROOT / "code/firmware/body/lib/TerminalIr/TerminalIr.h"
    ).read_text()
    assert "rmt_rx_start" in rmt
    assert 'v == "ir"' in protocol
    assert 'IrValid(json.get())' in bridge
    assert '{"/api/ir", HTTP_GET}' in bridge
    assert 'async def ir_status(self)' in transport
    assert '"/api/ir"' in transport
    assert '"/v1/robots/{robot_id}/dock/ir"' in api
    assert "charging_authorized" in (
        ROOT / "code/laptop/src/desk_robot/dock_ir.py"
    ).read_text()
    assert PLAN["bus"]["implementation_evidence"]["dual_ir_physical_qualified"] is False


def test_all_eight_tof_lanes_and_every_aux_lane_have_unique_i2c_addresses():
    ranges = PLAN["bus"]["mux_ranges"]
    extras = PLAN["bus"]["mux_extras"]
    assert ranges["address"] == 0x70
    assert extras["address"] == 0x71
    assert {x["channel"] for x in ranges["channels"]} == set(range(8))
    assert {x["channel"] for x in extras["channels"]} == set(range(8))
    assert [x["position"] for x in ranges["channels"][:5]] == [
        "floor_front_left", "floor_front_right", "floor_rear_left",
        "floor_rear_right", "front_obstacle",
    ]
    for group in (ranges, extras):
        for lane in group["channels"]:
            addresses = [device["address"] for device in lane["devices"]]
            assert all(type(a) is int and 0x08 <= a <= 0x77 for a in addresses)
            assert len(addresses) == len(set(addresses)), (
                group["address"], lane["channel"]
            )
    assert {
        (device["name"], device["address"])
        for device in extras["channels"][5]["devices"]
    } == {("PN532 I2C", 0x24), ("MCP23017", 0x20)}
    assert all(lane["devices"][0]["address"] == 0x29
               for lane in ranges["channels"])



@pytest.mark.parametrize("mutation", ["wrong_address", "extra_device", "missing_device", "bool_address", "wrong_name"])
def test_wiring_manifest_rejects_unqualified_range_lane_mutations(mutation):
    """Negative contract for the existing eight isolated native-address ToF lanes."""
    import copy
    import importlib.util

    module_path = ROOT / "code/scripts/emit_wiring_manifest.py"
    spec = importlib.util.spec_from_file_location("emit_wiring_manifest", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    body = (ROOT / module.BODY_PINS).read_text()
    head = (ROOT / module.HEAD_PINS).read_text()
    plan = copy.deepcopy(PLAN)
    module.verify(plan, body, head)
    devices = plan["bus"]["mux_ranges"]["channels"][0]["devices"]
    if mutation == "wrong_address":
        devices[0]["address"] = 0x30
    elif mutation == "extra_device":
        devices.append({"name": "unapproved sensor", "address": 0x30})
    elif mutation == "missing_device":
        devices.clear()
    elif mutation == "bool_address":
        devices[0]["address"] = True
    else:
        devices[0]["name"] = "unapproved range sensor"
    with pytest.raises(ValueError, match="I2C address|Range lane"):
        module.render(plan, body, head)


@pytest.mark.parametrize("mutation", ["wrong_expander_address", "wrong_expander_name", "missing_expander", "extra_device"])
def test_wiring_manifest_rejects_dock_expander_lane_drift(mutation):
    """Dock interlock harness must not silently substitute or move MCP23017."""
    import copy
    import importlib.util

    path = ROOT / "code/scripts/emit_wiring_manifest.py"
    spec = importlib.util.spec_from_file_location("emit_wiring_manifest", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    body = (ROOT / module.BODY_PINS).read_text()
    head = (ROOT / module.HEAD_PINS).read_text()
    plan = copy.deepcopy(PLAN)
    devices = plan["bus"]["mux_extras"]["channels"][5]["devices"]
    if mutation == "wrong_expander_address":
        devices[1]["address"] = 0x21
    elif mutation == "wrong_expander_name":
        devices[1]["name"] = "unknown expander"
    elif mutation == "missing_expander":
        devices.pop()
    else:
        devices.append({"name": "unexpected", "address": 0x30})
    with pytest.raises(ValueError, match="Dock accessory lane 5"):
        module.render(plan, body, head)


@pytest.mark.parametrize("group,channel", [
    ("mux_ranges", True), ("mux_ranges", 0.0),
    ("mux_extras", False), ("mux_extras", "0"),
])
def test_wiring_manifest_rejects_noninteger_mux_lane(group, channel):
    """Bool and coercible channel IDs must not masquerade as physical mux lanes."""
    import copy
    import importlib.util

    path = ROOT / "code/scripts/emit_wiring_manifest.py"
    spec = importlib.util.spec_from_file_location("emit_wiring_manifest", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    plan = copy.deepcopy(PLAN)
    plan["bus"][group]["channels"][0]["channel"] = channel
    body = (ROOT / module.BODY_PINS).read_text()
    head = (ROOT / module.HEAD_PINS).read_text()
    with pytest.raises(ValueError, match="Invalid or incomplete"):
        module.verify(plan, body, head)



@pytest.mark.parametrize("group,address", [
    ("mux_ranges", True), ("mux_ranges", 0x29 + 0.0),
    ("mux_extras", False), ("mux_extras", "0x20"),
])
def test_wiring_manifest_rejects_coercible_device_addresses(group, address):
    """A sensor or dock expander address must be a genuine 7-bit integer."""
    import copy
    import importlib.util

    path = ROOT / "code/scripts/emit_wiring_manifest.py"
    spec = importlib.util.spec_from_file_location("emit_wiring_manifest", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    plan = copy.deepcopy(PLAN)
    lane = 0 if group == "mux_ranges" else 5
    plan["bus"][group]["channels"][lane]["devices"][0]["address"] = address
    body = (ROOT / module.BODY_PINS).read_text()
    head = (ROOT / module.HEAD_PINS).read_text()
    with pytest.raises(ValueError, match="Invalid .* I2C address"):
        module.verify(plan, body, head)


def test_plan_source_owners_exist_without_implying_hardware_qualified():
    evidence = PLAN["bus"]["implementation_evidence"]
    for key in (
        "ranges", "raw_expansion", "touch", "pulse", "dock",
        "pet_consumer", "side_consumer", "full_profile", "test_contracts",
    ):
        assert (ROOT / evidence[key]).is_file(), f"Missing {key} owner"
    assert PLAN["target_robots"] == 5
    assert PLAN["physical_trial_count"] == 0
    assert evidence["sensor_hardware_qualified"] is False
    assert evidence["charging_current_electrically_verified"] is False


def test_auto_social_peer_requires_explicit_local_provenance_consent():
    settings = load_settings(ROOT / "code/config/fleet.simulation.toml")
    data = settings.model_dump()
    data["fleet_social_autonomy_enabled"] = True
    data["fleet_text_sharing_enabled"] = False
    with pytest.raises(ValidationError, match="local text sharing consent"):
        Settings.model_validate(data)
    data["fleet_text_sharing_enabled"] = True
    configured = Settings.model_validate(data)
    assert configured.fleet_social_autonomy_enabled
    assert configured.fleet_social_min_interval_seconds >= 30


def test_body_status_uart_capacity_covers_full_width_sensor_counters():
    # Source contract: status must still fit when 32-bit counters/age fields
    # reach their widest values. Default-zero examples miss this failure.
    import re

    body = (ROOT / "code/firmware/body/lib/BodyControl/BodyControl.cpp").read_text()
    header = (ROOT / "code/firmware/body/lib/BodyControl/BodyControl.h").read_text()
    bridge = (ROOT / "code/firmware/head/overlay/robot_bridge.cc").read_text()
    status = body.split("} else if (status) {", 1)[1]
    status = status.split('state_.armed ? "true"', 1)[0]
    status = status.split("const int written = std::snprintf(", 1)[1]
    parts = re.findall(r'"(?:\\.|[^"\\])*"', status)
    wire_format = "".join(json.loads(part) for part in parts)
    formats = re.findall(r"%(?:lu|u|d|s)", wire_format)
    assert len(formats) >= 55  # actual full sensor status, not a stub
    static_bytes = len(re.sub(r"%(?:lu|u|d|s)", "", wire_format))
    worst_case = static_bytes + sum(
        {"%lu": 10, "%u": 10, "%d": 11, "%s": 24}[field]
        for field in formats
    )
    body_capacity = int(re.search(r"kReplyCapacity\s*=\s*(\d+)", header).group(1))
    head_capacity = int(re.search(r"kMaxReply\s*=\s*(\d+)", bridge).group(1))
    rx_capacity = int(re.search(r"uart_driver_install\(kUart,\s*(\d+)", bridge).group(1))
    assert worst_case < body_capacity < head_capacity < rx_capacity


@pytest.mark.parametrize("group,address", [
    ("mux_ranges", 112.0), ("mux_ranges", "112"),
    ("mux_extras", 113.0), ("mux_extras", "113"),
])
def test_wiring_manifest_rejects_noninteger_mux_i2c_address(group, address):
    """Reject coercible mux addresses before formatting or exporting wiring."""
    import copy
    import importlib.util

    path = ROOT / "code/scripts/emit_wiring_manifest.py"
    spec = importlib.util.spec_from_file_location("emit_wiring_manifest", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    plan = copy.deepcopy(PLAN)
    plan["bus"][group]["address"] = address
    body = (ROOT / module.BODY_PINS).read_text()
    head = (ROOT / module.HEAD_PINS).read_text()
    with pytest.raises(ValueError, match="Incorrect .* mux address"):
        module.render(plan, body, head)
