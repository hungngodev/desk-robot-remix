"""Cross-layer contracts prevent accidental sensor and harness drift.

These are source assertions, never electrical, acoustic or safety acceptance.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from desk_robot.config import Settings, load_settings
from desk_robot.multimodal import TRIGGERS
from desk_robot.pet import (
    _DIRECT_INTERACTION_KINDS,
    _PHYSICAL_INITIATIVE_KINDS,
    _SOCIAL_EVENT_KINDS,
    _VISUAL_INITIATIVE_MIN_CONFIDENCE,
)
from desk_robot.sensor_event_contract import (
    DIRECT_INTERACTION_KINDS,
    PHYSICAL_INITIATIVE_KINDS,
)
from desk_robot.sensor_event_contract import (
    TRIGGERS as SHARED_TRIGGERS,
)
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
PLAN = json.loads((ROOT / "docs/hardware/full-feature-plan.json").read_text())


def test_one_shared_real_sensor_event_registry_owns_camera_and_pet_kinds():
    """Different owners cannot silently disagree on actual event names."""
    assert TRIGGERS is SHARED_TRIGGERS
    assert _PHYSICAL_INITIATIVE_KINDS is PHYSICAL_INITIATIVE_KINDS
    assert _DIRECT_INTERACTION_KINDS is DIRECT_INTERACTION_KINDS
    assert TRIGGERS - PHYSICAL_INITIATIVE_KINDS == {
        "human_voice", "safety_fault",
    }
    assert _DIRECT_INTERACTION_KINDS <= _PHYSICAL_INITIATIVE_KINDS


def test_required_nc_bumper_and_reed_are_real_but_pir_remains_lab_only():
    """Full builds require real fail-closed GPIO35, not unqualified PIR."""
    ini = (ROOT / "code/firmware/body/platformio.ini").read_text()
    main = (ROOT / "code/firmware/body/src/main.cpp").read_text()
    sensors = (ROOT / "code/firmware/body/lib/AccessorySensors/AccessorySensors.cpp").read_text()
    pet = (ROOT / "code/laptop/src/desk_robot/pet.py").read_text()
    full = ini.split("[env:esp32_full]", 1)[1].split("[env:", 1)[0]
    dc = ini.split("[env:esp32_dc_full]", 1)[1].split("[env:", 1)[0]
    lab = ini.split("[env:esp32_full_interaction_lab]", 1)[1].split("[env:", 1)[0]
    for profile in (full, dc):
        assert "-DDESK_ROBOT_ENABLE_REED=1" in profile
        assert "-DDESK_ROBOT_ENABLE_BUMPER=1" in profile
        assert "-DDESK_ROBOT_ENABLE_PIR=1" not in profile
    assert "-DDESK_ROBOT_ENABLE_PIR=1" in lab
    # Lab inherits the full guarded NC bumper profile rather than
    # redeclaring a second conflicting build flag.
    assert "build_flags = ${env:esp32_full.build_flags}" in lab
    assert "control.sample_bumper_input(digitalRead(body_pins::kBumperInput) == HIGH);" in main
    assert "write8(0x20, 0x0D, 0x01)" in sensors  # GPIOB0 pullup
    assert "extension_fresh" in main
    assert "mask |= 2U;" in main
    assert "(\"reed_count\", 2, \"magnet\"" in pet


def test_nc_bumper_is_sampled_before_bus_commands_and_motor_outputs():
    """The slow event classifier cannot own physical motor authorization."""
    body = (ROOT / "code/firmware/body/src/main.cpp").read_text()
    raw = body.split("bool sample_raw_bumper() {", 1)[1].split("void poll_optional", 1)[0]
    assert "control.sample_bumper_input(digitalRead(body_pins::kBumperInput) == HIGH);" in raw
    outputs = body.split("void apply_outputs() {", 1)[1].split("void process_input(", 1)[0]
    assert outputs.index("sample_raw_bumper();") < outputs.index("control.tick(")
    command = body.split("void process_input(", 1)[1].split("void setup()", 1)[0]
    assert command.index("if (sample_raw_bumper()) apply_outputs();") < command.index(
        "receiver.feed("
    )
    assert command.index("apply_outputs();  // apply accepted") < command.index(
        "desk_robot::MotionAckVeto::BumperActive"
    ) < command.index("replies.enqueue_line(reply)")
    loop = body.split("void loop() {", 1)[1]
    assert loop.index("if (sample_raw_bumper()) apply_outputs();") < loop.index("tof.poll(")
    assert loop.index("if (control.state().bumper_raw) apply_outputs();") < loop.index(
        "accessories.poll("
    )
    assert loop.rindex("sample_raw_bumper();") < loop.index("enforce_motor_heartbeat(true);")
    assert loop.rindex("sample_raw_bumper();") > loop.index("accessories.poll(")


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


def test_late_optional_mux_detection_reaches_active_tof_safety_owner():
    """A later CAP1188 0x29 must not bypass the earlier 0x71 startup NACK."""
    body = (ROOT / "code/firmware/body/src/main.cpp").read_text()
    # Runtime I2C behavior is tested in the native tof_mux and optional
    # sensor tests. Here pin only the cross-owner wiring in actual setup.
    setup = body.split("void setup()", 1)[1].split("void loop()", 1)[0]
    setup = re.sub(r"//[^\n]*|/\*.*?\*/", "", setup, flags=re.S)
    setup = re.sub(r"\s+", "", setup)
    required = "#ifDESK_ROBOT_EXTRA_RANGERStof.note_optional_mux_present();#endif"
    assert required in setup
    assert setup.index(required) < setup.index("tof.begin(")
    discovery = (
        "if(cap1188.present()||paw_pulse.mux_present()||accessories.mux_present())"
        "tof.note_optional_mux_present();"
    )
    assert discovery in setup
    assert setup.index("accessories.begin(Wire)") < setup.index(discovery)


def test_cliff_fault_reaches_motor_outputs_before_other_i2c_work():
    body = (ROOT / "code/firmware/body/src/main.cpp").read_text()
    loop = body.split("void loop()", 1)[1]
    loop = re.sub(r"//[^\n]*|/\*.*?\*/", "", loop, flags=re.S)
    loop = re.sub(r"\s+", "", loop)
    stop = "if(!cliff_guard.evaluate(millis()))apply_outputs();"
    assert loop.index("tof.poll(") < loop.index(stop) < loop.index("berry_imu.poll(")
    for client in ("berry_imu", "paw_pulse", "accessories"):
        assert f"if(tof.bus_accessible()){client}.poll(" in loop
    assert "if(tof.bus_accessible()&&cap1188.present())" in loop
    assert "elseif(!cap1188.verified())control.set_cap(false,0);" in loop
    assert loop.count("cap1188.invalidate_bus();") == 2
    assert "tof.observe_shared_bus_fault(cliff_guard);" in loop


def test_imu_fault_reaches_motor_outputs_before_optional_i2c_work():
    body = (ROOT / "code/firmware/body/src/main.cpp").read_text()
    loop = body.split("void loop()", 1)[1]
    loop = re.sub(r"//[^\n]*|/\*.*?\*/", "", loop, flags=re.S)
    loop = re.sub(r"\s+", "", loop)
    armed = "constboolwas_armed_before_imu=control.state().armed;"
    sample = "control.set_imu(berry_imu.reading());"
    stop = (
        "if(was_armed_before_imu&&"
        "(!control.state().armed||!control.imu_fresh(millis()))){apply_outputs();}"
    )
    assert loop.index(armed) < loop.index(sample) < loop.index(stop)
    for client in ("poll_touch(", "cap1188.poll(", "paw_pulse.poll(", "accessories.poll("):
        assert loop.index(stop) < loop.index(client, loop.index(sample))


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
    evidence = (ROOT / "code/firmware/body/lib/BodyControl/McpContactEvidence.h").read_text()
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
    assert "contact_evidence.observe(extension, now_ms)" in main
    assert "now_ms - sample.at_ms > 250U" in evidence
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



@pytest.mark.parametrize("lane,mutation", [
    (4, "swap_battery_monitor"),
    (4, "remove_fuel_gauge"),
    (6, "wrong_wheel_address"),
    (7, "extra_wheel_device"),
])
def test_wiring_manifest_rejects_battery_and_wheel_lane_drift(lane, mutation):
    """Do not mislabel pack monitoring or wheel encoder mux ownership."""
    import copy
    import importlib.util

    path = ROOT / "code/scripts/emit_wiring_manifest.py"
    spec = importlib.util.spec_from_file_location("emit_wiring_manifest", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    plan = copy.deepcopy(PLAN)
    devices = plan["bus"]["mux_extras"]["channels"][lane]["devices"]
    if mutation == "swap_battery_monitor":
        devices[0]["name"] = "MAX17048"
    elif mutation == "remove_fuel_gauge":
        devices.pop()
    elif mutation == "wrong_wheel_address":
        devices[0]["address"] = 0x37
    else:
        devices.append({"name": "unexpected", "address": 0x30})
    body = (ROOT / module.BODY_PINS).read_text()
    head = (ROOT / module.HEAD_PINS).read_text()
    with pytest.raises(ValueError, match=f"Accessory lane {lane} battery/wheel"):
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


@pytest.mark.parametrize("group", ["mux_ranges"])
def test_wiring_manifest_rejects_swapped_cliff_mux_channels(group):
    """A complete set of channels is insufficient if floor roles are swapped."""
    import copy
    import importlib.util

    path = ROOT / "code/scripts/emit_wiring_manifest.py"
    spec = importlib.util.spec_from_file_location("emit_wiring_manifest", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    plan = copy.deepcopy(PLAN)
    lanes = plan["bus"][group]["channels"]
    lanes[0]["channel"], lanes[1]["channel"] = lanes[1]["channel"], lanes[0]["channel"]
    body = (ROOT / module.BODY_PINS).read_text()
    head = (ROOT / module.HEAD_PINS).read_text()
    with pytest.raises(ValueError, match="Critical cliff/obstacle sensor channel mapping drift"):
        module.verify(plan, body, head)


def test_full_dc_firmware_profiles_enable_external_motor_watchdog_heartbeat():
    """Every full DC profile must emit the GPIO23 CPU-liveness pulse.

    This checks build configuration only, not physical CD74HC123 cutoff.
    """
    import configparser

    ini = configparser.ConfigParser(interpolation=None)
    ini.read(ROOT / "code/firmware/body/platformio.ini")
    full = ini["env:esp32_dc_full"]["build_flags"]
    assert "-DDESK_ROBOT_STEPPER=0" in full
    assert "-DDESK_ROBOT_FULL_SENSORS=1" in full
    assert "-DDESK_ROBOT_ENABLE_DC_WATCHDOG=1" in full
    # DC fault latching also needs a physical MCP23017 GPB3 connection.
    # Source ownership matters: a declaration alone cannot stop the wheels.
    assert "-DDESK_ROBOT_REQUIRE_DC_NFAULT=1" in full
    main = (ROOT / "code/firmware/body/src/main.cpp").read_text()
    body = (ROOT / "code/firmware/body/lib/BodyControl/BodyControl.cpp").read_text()
    inputs = (ROOT / "code/firmware/body/lib/AccessorySensors/AccessorySensors.cpp").read_text()
    assert "control.require_dc_driver_fault_monitor(true)" in main
    assert "extra.driver_fault_active = (bits & 0x08U) == 0" in inputs
    assert "dc_driver_fault_bad(now_ms)" in body
    assert "ERR arm dc_driver_fault_interlock" in body
    assert "ERR rearm dc_driver_fault_unhealthy" in body
    for profile in ("esp32_dc_watchdog_lab", "esp32_dc_integrated_lab"):
        assert ini[f"env:{profile}"]["extends"] == "env:esp32_dc_full"
    assert "-DDESK_ROBOT_ENABLE_DC_WATCHDOG=1" not in ini["env:esp32_full"]["build_flags"]

def test_wroom_motor_and_servo_ledc_timers_do_not_collide():
    """Round 2 audit: preserve native WROOM LEDC isolation, not ESP32Servo.

    This tests configured source channel ownership, not measured PWM waveforms.
    Arduino ESP32 2.x binds each channel pair to one timer within its group.
    """
    pins = (ROOT / "code/firmware/body/include/BodyPins.h").read_text()
    main = (ROOT / "code/firmware/body/src/main.cpp").read_text()
    ini = (ROOT / "code/firmware/body/platformio.ini").read_text()

    def channels(name):
        match = re.search(rf"constexpr int {name}\[\] = \{{([^}}]+)\}};", pins)
        assert match, name
        return [int(value.strip()) for value in match.group(1).split(",")]

    motors = channels("kMotorChannels")
    servos = channels("kServoChannels")
    # Treat any accidental PWM timer collision as a regression, even when
    # the channel numbers themselves happen to remain distinct.
    def timer(channel):
        return (channel % 8) // 2

    assert motors == [0, 1, 2, 3]
    assert servos == [4, 5]
    assert not ({timer(c) for c in motors} & {timer(c) for c in servos})
    assert "kMotorFrequency = 20000" in pins
    assert "kMotorResolution = 8" in pins
    assert "kServoFrequency = 50" in pins
    assert "kServoResolution = 16" in pins
    assert "static_assert(kMotorChannels[0] == 0" in pins
    assert "static_assert(kServoChannels[0] == 4" in pins
    assert "platform = espressif32@6.9.0" in ini  # frozen Arduino core mapping
    assert "#include <ESP32Servo.h>" not in main
    assert "analogWrite(" not in main
    for ch in range(4):
        assert f"body_pins::kMotorChannels[{ch}]" in main
    for ch in range(2):
        assert main.count(f"body_pins::kServoChannels[{ch}]") >= 3


def test_wroom_mux_reset_must_remain_hardware_pullup_not_boot_gpio():
    """Prevent a dangerous product document from overriding the real pins."""
    pins = (ROOT / "code/firmware/body/include/BodyPins.h").read_text()
    bus = (ROOT / "code/firmware/body/lib/TofBus/TofBus.cpp").read_text()
    main = (ROOT / "code/firmware/body/src/main.cpp").read_text()
    plan = (ROOT / "docs/product-definition.md").read_text()
    assert "constexpr int kMuxReset = -1;" in pins
    assert "static_assert(kMuxReset == -1" in pins
    assert "NO independent CPU-halt" in pins
    assert "if (mux_reset_pin >= 0)" in bus
    assert "body_pins::kMuxReset" in main
    assert "| TCA9548A reset | No GPIO, tied HIGH to 3.3 V" in plan
    assert "| Reserved body inputs | 35 NC bumper; 36/39 left/right terminal IR |" in plan
    assert "| TCA9548A reset | 4 |" not in plan


def test_documented_pet_voice_budget_matches_passive_and_touch_code():
    """Physical contact is deliberate, not a silent 120-second greeting."""
    pet = (ROOT / "code/laptop/src/desk_robot/pet.py").read_text()
    definition = (ROOT / "docs/product-definition.md").read_text()
    assert "speech_cooldown: float = 120.0" in pet
    assert "interaction_cooldown: float = 12.0" in pet
    assert "passive camera/ambient spontaneous spoken initiation" in definition
    assert "default 12-second interaction cooldown" in definition
    assert "single global speaker" in definition


def test_round2_safety_driver_preserves_all_eight_muxed_ready_checked_ranges():
    """No two-XSHUT or two-sample cliff replacement can silently land."""
    body = (ROOT / "code/firmware/body/lib/TofBus/TofBus.cpp").read_text()
    header = (ROOT / "code/firmware/body/lib/TofBus/TofBus.h").read_text()
    guard = (ROOT / "code/firmware/body/lib/CliffGuard/CliffGuard.cpp").read_text()
    plan = PLAN["bus"]
    assert plan["mux_ranges"]["address"] == 0x70
    assert len(plan["mux_ranges"]["channels"]) == 8
    assert "kRangeCount = 5 + (DESK_ROBOT_EXTRA_RANGERS ? 3 : 0)" in header
    assert "kSensorAddress = 0x29" in header
    assert "read_register(0x13, &ready, 1)" in body
    assert "read_register(0x14, result, kMaxSampleBytes)" in body
    assert "sensor.startContinuous()" in body
    assert "readRangeSingleMillimeters(" not in body
    assert "readRangeContinuousMillimeters(" not in body
    assert "guard.sample(channel, distance, accepted, now_ms)" in body
    assert "if (configured_) latch(sample_fault(channel), channel)" in guard
    assert "latch(CliffFault::BusFailure)" in guard
    assert "bool CliffGuard::try_rearm" in guard
    assert "GPIO_NUM_18" not in (
        ROOT / "code/firmware/head/sense/config.h"
    ).read_text().split("#define CAMERA_PIN_D2")[0]

def test_round2_xiaozhi_jpeg_and_bounded_uart_reuse_existing_owners():
    """Prove the audit's alternate S3CAM UART/Explain loop is not installed.

    Static source ownership, not a physical camera FPS or playback latency test.
    """
    sense = (ROOT / "code/firmware/head/sense/desk_robot_sense.cc").read_text()
    sense_pins = (ROOT / "code/firmware/head/sense/config.h").read_text()
    bridge = (ROOT / "code/firmware/head/overlay/robot_bridge.cc").read_text()
    overlay = (ROOT / "code/firmware/head/install_overlay.py").read_text()
    snapshot = (ROOT / "code/firmware/head/modular_snapshot.inc").read_text()
    body = (ROOT / "code/firmware/body/src/main.cpp").read_text()
    config = (ROOT / "code/config/xiaozhi.local.example.yaml").read_text()

    # XIAO Sense streams JPEG using the existing single upstream Xiaozhi
    # camera. Two PSRAM frame buffers are necessary for Espressif's continuous
    # JPEG acquisition; LATEST avoids handing a queued older frame to Mac.
    # The single owner is a camera instance, not a single frame buffer.
    assert "config.pixel_format = PIXFORMAT_JPEG" in sense
    assert "config.fb_count = 2;" in sense
    assert "config.grab_mode = CAMERA_GRAB_LATEST;" in sense
    assert "config.fb_location = CAMERA_FB_IN_PSRAM" in sense
    assert "void Bridge::CameraStreamTask(" in bridge
    assert '"/api/camera.mjpg"' in bridge
    assert '"/api/camera.identity"' in bridge
    assert 'esp_camera_sensor_get()' in bridge
    assert 'pid == OV3660_PID' in bridge and 'pid == OV5640_PID' in bridge
    assert '"camera_pid_raw"' in bridge and '"boot"' in bridge
    assert "camera_busy_.exchange(true)" in bridge
    assert "SnapshotJpeg()" in bridge and "SnapshotJpeg()" in snapshot
    assert "std::lock_guard<std::recursive_mutex> camera_lock(AccessMutex())" in snapshot
    assert 'if board == "sense":' in overlay
    assert "CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3" in overlay
    assert "LAMP_GPIO" not in sense_pins
    # GPIO18 is genuinely used by OV camera D2, not a second LED or lamp.
    assert "#define CAMERA_PIN_D2 GPIO_NUM_18" in sense_pins

    # The WROOM retains a 64-byte per-iteration inbound UART budget. It
    # replies only to bounded requests, never streams 100 Hz IMU or ToF logs
    # into Xiaozhi's audio thread, and makes no unsolicited motor decisions.
    assert "for (int bytes = 0; bytes < 64 && stream.available() > 0;" in body
    # The bounded head input still feeds the canonical WROOM controller,
    # but long status replies are enqueued instead of blocking the cliff and
    # heartbeat loop for an entire 115200-baud JSON transmission.
    assert "process_input(head_uart, head_receiver, head_replies, false);" in body
    assert "process_input(Serial, usb_receiver, usb_replies, true);" in body
    assert "replies.enqueue_line(reply);" in body
    assert "head_replies.drain(head_uart);" in body
    assert "usb_replies.drain(Serial);" in body
    assert "stream.print(reply)" not in body
    assert "uart_driver_install(kUart, 2048," in bridge
    assert 'Transact("status", false)' in bridge
    assert "Serial2.printf" not in body
    assert "EVT:CLIFF" not in body
    # All live model tools remain on the existing XiaoZhi function_call
    # route and Mac read-only bridge. No extra VLLM or cloud agent required.
    assert "Intent: function_call" in config
    assert "LLM: OllamaLLM" in config

def test_pinned_sense_sensor_tool_alias_is_only_readonly_live_wroom():
    """Expose sensory context without granting the model motor authority.

    The actual Sense ESP-IDF build will also compile this MCP registration.
    This source contract cannot certify electrical, voice or sensor hardware.
    """
    bridge = (ROOT / "code/firmware/head/overlay/robot_bridge.cc").read_text()
    sense = (ROOT / "code/firmware/head/sense/desk_robot_sense.cc").read_text()
    user_tools = bridge.split("void Bridge::AddTools() {", 1)[1]
    alias = user_tools.split(
        'mcp.AddTool(\n        "self.pet.get_sensory_state",', 1
    )[1].split("#ifdef CONFIG_DESK_ROBOT_DIRECT_MOTION_TOOLS", 1)[0]
    assert 'return call("status");' in alias
    assert "PropertyList()" in alias
    assert "Read the current WROOM cliff safety" in alias
    assert "motor permission" in alias
    assert 'mcp.AddTool("self.robot.drive"' in user_tools
    assert "#ifdef CONFIG_DESK_ROBOT_DIRECT_MOTION_TOOLS" in user_tools
    assert 'self.pet.move' not in user_tools
    assert 'self.pet.calibrate_sensors' not in user_tools
    # Long sensor narratives are never sent as invalid wake-word detect
    # payloads. The selected Sense board already reuses an opt-in Xiaozhi
    # audio turn, which has independent human interruption and consent.
    assert "WakeWordInvoke(" not in sense
    assert "SendWakeWordDetected(" not in sense
    assert "WakeWordInvoke(" not in bridge
    assert "SendWakeWordDetected(" not in bridge
    assert "CONFIG_DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED" in sense


def test_legacy_esp32dev_firmware_is_actuator_inert_without_full_safety():
    """Historical compatibility flashing must never drive wheels or servos."""
    ini = (ROOT / "code/firmware/body/platformio.ini").read_text()
    main = (ROOT / "code/firmware/body/src/main.cpp").read_text()
    control = (ROOT / "code/firmware/body/lib/BodyControl/BodyControl.cpp").read_text()
    legacy = ini.split("[env:esp32dev]", 1)[1].split("[env:", 1)[0]
    assert "-DDESK_ROBOT_STEPPER=0 -DDESK_ROBOT_FULL_SENSORS=0" in legacy

    # The same early guard applies to any future unguarded compatibility env.
    outputs = main.split("void apply_outputs() {", 1)[1].split("void process_input(", 1)[0]
    inert = outputs.split("#if !DESK_ROBOT_FULL_SENSORS", 1)[1].split("#endif", 1)[0]
    assert "control.force_disarm();" in inert
    assert "zero_motor_pwm();" in inert
    assert "return;" in inert
    assert outputs.index("#if !DESK_ROBOT_FULL_SENSORS") < outputs.index(
        "if (state.servos_attached"
    )
    assert "#if !DESK_ROBOT_FULL_SENSORS ||" in main
    assert "control.inhibit_unqualified_motor_cutoff();" in main
    assert '"ERR arm motor_cutoff_unqualified"' in control


@pytest.mark.parametrize(("lane", "index", "field", "value"), [
    (0, 0, "address", 0x2A),
    (0, 1, "address", 0x56),
    (0, 0, "name", "unapproved touch sensor"),
    (1, 0, "address", 0x38),
    (1, 1, "address", 0x37),
    (2, 0, "address", 0x49),
    (3, 0, "address", 0x45),
    (3, 1, "address", 0x75),
    (3, 1, "name", "BME280"),
])
def test_wiring_manifest_rejects_interaction_sensor_lane_drift(lane, index, field, value):
    """A valid seven-bit address is insufficient if firmware cannot read it."""
    import copy
    import importlib.util

    path = ROOT / "code/scripts/emit_wiring_manifest.py"
    spec = importlib.util.spec_from_file_location("emit_wiring_manifest", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    plan = copy.deepcopy(PLAN)
    plan["bus"]["mux_extras"]["channels"][lane]["devices"][index][field] = value
    body = (ROOT / module.BODY_PINS).read_text()
    head = (ROOT / module.HEAD_PINS).read_text()
    with pytest.raises(ValueError, match=f"Accessory lane {lane} sensor identity drift"):
        module.render(plan, body, head)


@pytest.mark.parametrize(("lane", "index", "address"), [(0, 0, 0x28), (3, 1, 0x77)])
def test_wiring_manifest_preserves_supported_accessory_address_straps(lane, index, address):
    """The existing CAP1188 and BMP280 drivers support both address straps."""
    import copy
    import importlib.util

    path = ROOT / "code/scripts/emit_wiring_manifest.py"
    spec = importlib.util.spec_from_file_location("emit_wiring_manifest", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    plan = copy.deepcopy(PLAN)
    plan["bus"]["mux_extras"]["channels"][lane]["devices"][index]["address"] = address
    body = (ROOT / module.BODY_PINS).read_text()
    head = (ROOT / module.HEAD_PINS).read_text()
    module.verify(plan, body, head)


def test_dc_output_helpers_follow_the_cutoff_build_guard():
    """Diagnostic and cutoff-disabled DC builds omit unused drive helpers."""
    main = (ROOT / "code/firmware/body/src/main.cpp").read_text()
    guard = (
        "#if !DESK_ROBOT_STEPPER && "
        "DESK_ROBOT_FULL_SENSORS && DESK_ROBOT_DC_HARDWARE_CUTOFF_QUALIFIED"
    )
    assert guard + "\nint applied_left = 0;\nint applied_right = 0;\n#endif" in main
    assert guard + "\nvoid write_motor_pair(" in main
    assert "#elif DESK_ROBOT_STEPPER\nvoid write_stepper(" in main
    outputs = main.split("void apply_outputs() {", 1)[1]
    cutoff = "#if DESK_ROBOT_FULL_SENSORS && !DESK_ROBOT_DC_HARDWARE_CUTOFF_QUALIFIED"
    off, on = outputs.split(cutoff, 1)[1].split("#else", 1)
    assert "zero_motor_pwm();" in off
    assert "write_motor_pair(" not in off
    assert "write_motor_pair(" in on.split("#endif", 1)[0]
