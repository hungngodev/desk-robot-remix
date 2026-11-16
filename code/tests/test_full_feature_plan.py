"""Machine check the chosen full-feature five-pet hardware electrical plan."""
import json
from pathlib import Path

PLAN = Path(__file__).resolve().parents[2] / "docs/hardware/full-feature-plan.json"


def load():
    return json.loads(PLAN.read_text(encoding="utf-8"))


def test_five_full_pets_and_reported_motor_stock():
    p = load()
    assert p["target_robots"] == 5
    parts = {x["id"]: x for x in p["parts"]}
    assert parts["stepper"]["per_robot"] == 2
    assert parts["stepper"]["reported_owned_total"] == 5
    assert parts["uln2003"]["per_robot"] == 2
    assert parts["mg90s"]["per_robot"] == 2
    assert parts["imu"]["per_robot"] == 1
    assert parts["cliff_obstacle"]["per_robot"] == 8
    assert parts["i2c_mux"]["per_robot"] == 2
    assert parts["head_touch"]["reported_owned_total"] >= 1
    assert parts["cap1188"]["per_robot"] == 1
    assert p["qualified_assumptions"] is False
    assert p["physical_trial_count"] == 0


def test_no_wroom_gpio_collisions_and_sense_pin_budget():
    p = load()
    for controller in ("body_gpio", "sense_gpio"):
        arrays = p["bus"][controller]
        pins = [pin for v in arrays.values() for pin in (v if isinstance(v, list) else [v])]
        assert len(pins) == len(set(pins)), f"Duplicate {controller} GPIO"
    b = p["bus"]["body_gpio"]
    assert b["head_touch"] == 34 and b["bumper_nc_series"] == 35
    source = (Path(__file__).resolve().parents[1] / "firmware/body/src/main.cpp").read_text()
    assert "bumper = digitalRead(body_pins::kBumperInput) == HIGH" in source
    assert "NC contacts in series" in p["bus"]["voltage_policy"]
    assert b["sda"] == 21 and b["scl"] == 22
    assert set(b["left_stepper"] + b["right_stepper"]) == {13,14,25,26,27,32,33,23}
    assert p["bus"]["sense_gpio"]["rgb_data"] == 9


def test_two_isolated_muxes_and_device_address_conflicts():
    p = load()
    bus = p["bus"]
    assert {d["address"] for d in bus["upstream"]} == {0x68, 0x70, 0x71}
    assert bus["mux_ranges"]["address"] == 0x70
    assert bus["mux_extras"]["address"] == 0x71
    for which in ("mux_ranges", "mux_extras"):
        channels = bus[which]["channels"]
        assert sorted(ch["channel"] for ch in channels) == list(range(8))
        for ch in channels:
            addresses = [d["address"] for d in ch["devices"]]
            assert len(addresses) == len(set(addresses)), (which, ch)
            assert all(0x08 <= addr <= 0x77 for addr in addresses)
    assert all(ch["devices"][0]["address"] == 0x29 for ch in bus["mux_ranges"]["channels"])
    cap = bus["mux_extras"]["channels"][0]["devices"][0]
    assert cap["name"] == "CAP1188" and cap["address"] == 0x28
    assert {d["name"] for d in bus["mux_extras"]["channels"][5]["devices"]} == {"PN532 I2C","MCP23017"}


def test_no_unearned_hardware_acceptance():
    p = load()
    assert p["prices_complete"] is False
    assert p["physical_trial_count"] == 0
    assert "never" in p["bus"]["critical_policy"].lower()
    source = (Path(__file__).resolve().parents[1] / "firmware/body/lib/TofBus/TofBus.cpp").read_text()
    assert "kOptionalMuxAddress" in source
    assert "quiesce_optional_mux()" in source
    assert "optional_mux_present_" in source
    assert "two servo" in p["bus"]["pca9685_policy"].lower()

def test_status_uart_and_usb_bounds_are_consistent_after_petting_telemetry():
    root = Path(__file__).resolve().parents[1]
    body = (root / "firmware/body/lib/BodyControl/BodyControl.h").read_text()
    bridge = (root / "firmware/head/overlay/robot_bridge.cc").read_text()
    usb = (root / "scripts/serial_bench.py").read_text()
    assert "kReplyCapacity = 1536" in body
    assert "kMaxReply = 1664" in bridge
    assert "port.readline(1664)" in usb



def test_canonical_driver_statuses_match_current_source_without_claiming_hardware():
    """Keep parallel chats from resurrecting old unimplemented driver labels."""
    p = load()
    bus = p["bus"]
    for channel in bus["mux_ranges"]["channels"][5:]:
        assert "implemented_read_only" in channel["firmware"]
        assert "not_physically_qualified" in channel["firmware"]
    for channel in bus["mux_extras"]["channels"]:
        assert channel["firmware"].startswith("implemented_")
    assert "pn532_read_only_unverified" in bus["mux_extras"]["channels"][5]["firmware"]
    assert "PN532" in next(x["name"] for x in p["parts"] if x["id"] == "pn532")
    assert bus["implementation_evidence"]["sensor_hardware_qualified"] is False
    assert bus["implementation_evidence"]["charging_current_electrically_verified"] is False
    root = Path(__file__).resolve().parents[1]
    extra = (root / "firmware/body/lib/AccessorySensors/AccessorySensors.cpp").read_text()
    body = (root / "firmware/body/lib/BodyControl/BodyControl.cpp").read_text()
    full = (root / "firmware/body/platformio.ini").read_text()
    main = (root / "firmware/body/src/main.cpp").read_text()
    assert "dock_status(now_ms)" in extra
    assert "dock.sample_seq = next_nonzero_sensor_sequence(dock.sample_seq)" in extra
    assert "dock_telemetry_bad(now_ms)" in body
    assert "const bool contact = dock.input_good || dock.left_seated ||" in body
    assert "dock.right_seated || dock.charge_indicated" in body
    assert "-DDESK_ROBOT_REQUIRE_DOCK_MONITOR=1" in full
    assert "control.require_dock_monitor(true)" in main
    # No claim of safe automatic charger enable or measured battery current.
    assert p["physical_trial_count"] == 0


def test_vl53l0x_probe_is_isolated_from_production_cliff_driver():
    """A low-cost range experiment must never silently change the safety build."""
    root = Path(__file__).resolve().parents[1]
    pio = (root / "firmware/body/platformio.ini").read_text()
    probe = (root / "firmware/body/src/vl53l0x_bench.cpp").read_text()
    production = (root / "firmware/body/lib/TofBus/TofBus.cpp").read_text()
    assert "build_src_filter = +<*> -<vl53l0x_bench.cpp>" in pio
    assert "build_src_filter = -<*> +<vl53l0x_bench.cpp>" in pio
    assert "https://github.com/pololu/vl53l0x-arduino.git#1.3.1" in pio
    assert "https://github.com/pololu/vl53l4cd-arduino.git#bc865905" in pio
    assert "#include <VL53L0X.h>" in probe
    assert "BENCH_ONLY" in probe and "digitalWrite(pin, LOW)" in probe
    assert "Wire.read() == (1U << kSensorChannel)" in probe
    assert "readRangeContinuousMillimeters()" in probe
    assert "sensor.setTimeout(80)" in probe
    assert "VL53L4CD" in production and "read_register(0x0089" in production
    assert "VL53L0X" not in production

def test_live_dock_ir_requires_real_receiver_and_beacon_purchase_slots():
    """A double demodulator in firmware still needs a real transmitting dock."""
    p = load()
    parts = {part["id"]: part for part in p["parts"]}
    assert parts["dock_ir_receivers"]["per_robot"] == 2
    assert parts["dock_ir_beacon_controller"]["per_robot"] == 1
    assert parts["dock_ir_emitter_channels"]["per_robot"] == 2
    assert all(parts[k]["reported_owned_total"] == 0 for k in (
        "dock_ir_receivers", "dock_ir_beacon_controller",
        "dock_ir_emitter_channels",
    ))
    assert p["target_robots"] * parts["dock_ir_receivers"]["per_robot"] == 10
    assert p["target_robots"] * parts["dock_ir_emitter_channels"]["per_robot"] == 10
    assert p["physical_trial_count"] == 0
    body_ir = (Path(__file__).resolve().parents[1] /
               "firmware/body/lib/TerminalIr/NecBurst.h").read_text()
    assert "decode_nec" in body_ir
    assert "motor_authorized = false" in body_ir
    assert "charging_authorized = false" in body_ir



def test_complete_robot_is_default_without_losing_guarded_dc_variant():
    """Building the default must not ship the old five-channel test profile."""
    root = Path(__file__).resolve().parents[1]
    pio = (root / "firmware/body/platformio.ini").read_text()
    main = (root / "firmware/body/src/main.cpp").read_text()
    body = (root / "firmware/body/lib/BodyControl/BodyControl.cpp").read_text()
    assert "default_envs = esp32_full" in pio
    assert "-DDESK_ROBOT_EXTRA_RANGERS=1" in pio
    assert "-DDESK_ROBOT_REQUIRE_DOCK_MONITOR=1" in pio
    assert "[env:esp32_dc_full]" in pio
    assert "-DDESK_ROBOT_FULL_SENSORS=1" in pio
    assert "BodyProfile::DcGuarded" in main
    assert "control.require_dock_monitor(true)" in main
    assert "control.require_imu_for_motion(true)" in main
    assert "guarded_motion_profile()" in body
    assert 'profile_ == BodyProfile::DcGuarded ? "dc_pwm_guarded"' in body
