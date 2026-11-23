"""Machine check the chosen full-feature five-pet hardware electrical plan."""
import json
import re
import runpy
from pathlib import Path

import pytest

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
    assert cap["name"] == "CAP1188" and cap["address"] == 0x29
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
    # These values grow when another optional sensor field joins status.
    # Check the real source contract instead of freezing the old constants.
    body_cap = int(re.search(r"kReplyCapacity\s*=\s*(\d+)", body).group(1))
    head_cap = int(re.search(r"kMaxReply\s*=\s*(\d+)", bridge).group(1))
    rx_cap = int(re.search(r"uart_driver_install\(kUart,\s*(\d+)", bridge).group(1))
    usb_cap = int(re.search(r"port\.readline\((\d+)\)", usb).group(1))
    assert 0 < body_cap < head_cap < rx_cap
    assert usb_cap == head_cap



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


def test_low_cost_vl53l0x_is_the_production_cliff_driver():
    """The cheap sensor is selected for all guarded motor profiles."""
    root = Path(__file__).resolve().parents[1]
    pio = (root / "firmware/body/platformio.ini").read_text()
    probe = (root / "firmware/body/src/vl53l0x_bench.cpp").read_text()
    production = (root / "firmware/body/lib/TofBus/TofBus.cpp").read_text()
    header = (root / "firmware/body/lib/TofBus/TofBus.h").read_text()
    assert "build_src_filter = +<*> -<vl53l0x_bench.cpp>" in pio
    assert "build_src_filter = -<*> +<vl53l0x_bench.cpp>" in pio
    assert pio.count("https://github.com/pololu/vl53l0x-arduino.git#1.3.1") >= 4
    assert "vl53l4cd-arduino.git" not in pio
    assert "#include <VL53L0X.h>" in probe
    assert "#include <VL53L0X.h>" in header
    assert "sensor.init()" in production
    assert "read_register(0x13" in production
    assert "read_register(0x14" in production
    assert "write_byte(0x0B, 0x01)" in production
    assert "distance >= 30" in production
    assert "VL53L4CD" not in production

def test_boot_range_diagnostics_name_real_chip_and_guard_coverage():
    """A cheap VL53L0X fault must not tell the builder to buy VL53L4CD."""
    source = (Path(__file__).resolve().parents[1] /
              "firmware/body/src/main.cpp").read_text()
    assert "five_critical_vl53l0x_channels" in source
    assert "five_critical_vl53l0x_channels_three_diagnostic" in source
    assert "five_vl53l4cd_channels" not in source
    assert "check_mux_0x70" in source


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


def test_third_party_notice_and_hardware_source_map_dont_reintroduce_premium_sensor():
    root = Path(__file__).resolve().parents[2]
    notices = (root / "code/firmware/body/THIRD_PARTY_NOTICES.md").read_text()
    source_map = (root / "docs/source-map.md").read_text()
    pio = (root / "code/firmware/body/platformio.ini").read_text()
    assert "Pololu's VL53L0X Arduino library" in notices
    assert "release 1.3.1" in notices
    assert "VL53L4CD dependency is no longer selected" in notices
    assert "vl53l4cd-arduino" not in pio
    assert "VL53L4CD short-range replacement | REJECT PREMIUM PURCHASE" in source_map
    assert "OOMWOO is still in hardware development" in source_map


def test_superseded_decision_log_cannot_reselect_premium_tof():
    root = Path(__file__).resolve().parents[2]
    log = (root / "docs/decision-log.md").read_text()
    row = next(
        line for line in log.splitlines()
        if line.startswith("| Edge sensing (historical proposal, superseded) |")
    )
    assert "obsolete and not current purchasing selections" in row
    assert "8 generic VL53L0X GY-530 sensors per robot" in row
    assert "2 TCA9548A multiplexers" in row
    assert "physical qualification" in row
    assert "selected full source has eight VL53L4CDs" not in row


def test_active_product_docs_and_workflow_cannot_resurrect_premium_ranger():
    """Historical research may retain VL53L4CD; current active guides may not."""
    root = Path(__file__).resolve().parents[2]
    current = [
        ".github/workflows/host-verification.yml",
        "code/laptop/src/desk_robot/side_ranging.py",
        "code/scripts/calibrate_side_ranges.py",
        "docs/guides/interfaces.md",
        "docs/guides/pickup-and-two-robots.md",
        "docs/guides/side-ranging-proactive-perception.md",
        "docs/product-definition.md",
        "docs/hardware/interaction-sensors.md",
    ]
    for rel in current:
        body = (root / rel).read_text()
        assert "VL53L4CD" not in body, rel
        assert "VL53L0X" in body, rel
    agents = (root / "AGENTS.md").read_text()
    assert "Buy only cost-justified generic VL53L0X" in agents
    wiring = (root / "docs/hardware/wiring.md").read_text()
    assert "pinned MIT Pololu VL53L0X 1.3.1" in wiring
    assert "expensive VL53L4CD boards" in wiring
    assert "Historic VL6180X and VL53L0X suggestions are" not in wiring



def test_superseded_procurement_banner_cannot_recommend_premium_rangers():
    """An obsolete report may retain history, but its current banner must be correct."""
    root = Path(__file__).resolve().parents[2]
    body = (root / "docs/hardware/procurement-pass-2026-11-10.md").read_text()
    banner = body.splitlines()[0]
    assert "SUPERSEDED" in banner
    assert "40 generic VL53L0X GY-530" in banner
    assert "10 TCA9548A" in banner
    assert "NOT authorized purchases" in banner
    assert "40 VL53L4CD" not in banner
    assert "subject to verifying" in banner

def test_usb_calibration_and_cliff_guard_match_real_tof_source_valid_range():
    """Reject 1mm/15mm calibrations for a driver that discards <30mm."""
    import re
    root = Path(__file__).resolve().parents[1]
    driver = (root / "firmware/body/lib/TofBus/TofBus.cpp").read_text()
    controller = (root / "firmware/body/lib/BodyControl/BodyControl.cpp").read_text()
    guard = (root / "firmware/body/lib/CliffGuard/CliffGuard.cpp").read_text()
    matched = re.search(r"distance\s*>=\s*(\d+)\s*&&\s*distance\s*<=\s*(\d+)",
                        driver)
    assert matched is not None
    accepted_min, accepted_max = map(int, matched.groups())
    assert accepted_min == 30 and accepted_max == 1300
    # Three independently implemented source owners must agree, or CI fails.
    assert f"floor.min_mm < {accepted_min}" in guard
    assert f"floor.max_mm > {accepted_max}" in guard
    assert f"config.front_obstacle_mm < {accepted_min}" in guard
    assert f"config.front_max_mm > {accepted_max}" in guard
    assert f"minimum < {accepted_min}" in controller
    assert f"maximum > {accepted_max}" in controller
    assert f"near_mm < {accepted_min}" in controller
    assert f"far_mm > {accepted_max}" in controller


def test_full_fleet_speaker_source_is_exact_2w_and_remains_physical_hold():
    """Replace the unsafe 1W cart entry, not the thermal/fit acceptance gate."""
    p = load()
    speaker = next(x for x in p["parts"] if x["id"] == "speaker")
    assert "CS20-02P110-04-1X" in speaker["name"]
    assert "8 ohm 2 watt" in speaker["name"]
    assert "MAX98357A 5V output" in speaker["notes"]
    assert "1.8W" in speaker["notes"]
    assert "1cc sealed enclosure" in speaker["notes"]
    register = (PLAN.parent / "2026-11-16-five-pet-purchase-register.md").read_text()
    row = next(x for x in register.splitlines()
               if x.startswith("| " + chr(96) + "speaker" + chr(96) + " |"))
    fields = [v.strip() for v in row.strip().strip("|").split("|")]
    assert fields[8] == "0" and "EXACT SKU SOURCE SELECTED, NOT RELEASED" in row
    from pathlib import Path
    fit = Path(__file__).resolve().parents[2] / (
        "docs/cad/remixes/speaker_rect_fit_gauge.scad"
    )
    source = fit.read_text(encoding="utf-8")
    assert "CS20-02P110-04-1X" in source
    assert "speaker_l=20;" in source
    assert "speaker_w=16;" in source
    assert "speaker_h=4.7;" in source
    # The selected amp's nominal gain is a documented, inspectable hardware
    # assumption, never an accidental generic-breakout default or AEC pass.
    wiring = (Path(__file__).resolve().parents[2] /
              "docs/hardware/wiring.md").read_text(encoding="utf-8")
    assert "MAX98357A I2S GAIN and acoustic baseline" in wiring
    assert "floating for the nominal **+9 dB I2S gain**" in wiring
    assert "exact carrier revision, GAIN silkscreen" in wiring
    assert "invalidates the previous acoustic tuning" in wiring
    assert "at least 19/20 stops within 500 ms" in wiring
    assert "Neither the proposed +9 dB gain" in wiring






def test_usb_bench_exposes_only_raw_mpu_free_fall_counter():
    """A physical calibration operator needs IRQ count, not inferred drop."""
    bench = runpy.run_path(str(
        Path(__file__).resolve().parents[1] / "scripts/serial_bench.py"
    ))
    observe = bench["inspect_native_low_g"]
    raw = {"low_g_valid": True, "low_g_irq": True, "low_g_seq": 1}
    result = observe(raw, 4, True)
    assert result == {
        "reported": True, "status_valid": True,
        "interrupt_in_last_sample": True, "event_seq": 1,
        "physical_qualification_pass": False,
    }
    after_irq = {**raw, "low_g_irq": False}
    assert observe(after_irq, 4, True)["event_seq"] == 1
    assert not observe(after_irq, 4, True)["interrupt_in_last_sample"]
    assert not observe({}, 4, True)["reported"]
    assert observe({
        "low_g_valid": False, "low_g_irq": False, "low_g_seq": 1,
    }, 4, False)["event_seq"] == 1
    assert not observe({
        "low_g_valid": False, "low_g_irq": False, "low_g_seq": 0,
    }, 0, False)["status_valid"]

    for invalid, family, valid in (
        ({"low_g_valid": True}, 4, True),
        ({**raw, "low_g_valid": 1}, 4, True),
        ({**raw, "low_g_irq": 1}, 4, True),
        ({**raw, "low_g_seq": True}, 4, True),
        ({**raw, "low_g_seq": -1}, 4, True),
        ({**raw, "low_g_seq": 0}, 4, True),
        ({**raw, "low_g_seq": 0x100000000}, 4, True),
        ({**raw, "low_g_valid": False}, 4, True),
        (raw, 1, True),
        (raw, 4, False),
    ):
        with pytest.raises(ValueError, match="free-fall"):
            observe(invalid, family, valid)


def test_usb_bench_real_body_status_includes_native_low_g_without_release():
    bench = runpy.run_path(str(
        Path(__file__).resolve().parents[1] / "scripts/serial_bench.py"
    ))
    status = {
        "backend": "stepper_28byj48", "armed": False,
        "touch": {"active": False},
        "safety": {"ready": False, "fault": "not_required"},
        "ranges": {
            "present_mask": 0, "valid_mask": 0,
            "mm": [0] * 5, "age_ms": [0] * 5,
        },
        "imu": {
            "family": 4, "gyro_id": 0x68, "aux_id": 0,
            "valid": True, "acc": [0, 0, 16384], "gyro": [0, 0, 0],
            "age_ms": 20, "boot_id": 19, "sample_ms": 123456,
            "low_g_valid": True, "low_g_irq": False, "low_g_seq": 3,
        },
    }
    report = bench["inspect_status"](status)
    assert report["imu"]["native_low_g"]["event_seq"] == 3
    assert report["imu"]["source_boot_id"] == 19
    assert report["imu"]["source_sample_ms"] == 123456
    assert report["imu"]["native_low_g"]["reported"] is True
    assert report["imu"]["native_low_g"]["physical_qualification_pass"] is False
    assert report["physical_qualification_pass"] is False
    assert report["eligible_for_manual_local_rearm"] is False
    for corrupt in (
        {"boot_id": 0},
        {"boot_id": True},
        {"boot_id": "19"},
        {"sample_ms": -1},
        {"sample_ms": True},
        {"sample_ms": 0x100000000},
    ):
        bad = {**status, "imu": {**status["imu"], **corrupt}}
        with pytest.raises(ValueError, match="source identity"):
            bench["inspect_status"](bad)
    bad = {**status, "imu": {**status["imu"]}}
    del bad["imu"]["sample_ms"]
    with pytest.raises(ValueError, match="source identity"):
        bench["inspect_status"](bad)
    # DC may use the same selected MPU for bench INSPECTION. This helper
    # must never infer DC rearm eligibility from five healthy optical beams,
    # because independent nFAULT/dock/watchdog hardware is not qualified.
    dc = {
        **status, "backend": "dc_pwm_guarded",
        "ranges": {
            "present_mask": 31, "valid_mask": 31,
            "mm": [500] * 5, "age_ms": [20] * 5,
        },
    }
    dc_report = bench["inspect_status"](dc)
    assert dc_report["imu"]["native_low_g"]["event_seq"] == 3
    assert dc_report["eligible_for_manual_local_rearm"] is False
    for unguarded in ("dc_pwm", "simulator", "unknown"):
        with pytest.raises(ValueError, match="guarded"):
            bench["inspect_status"]({**dc, "backend": unguarded})


def test_first_unit_spatial_retrieval_is_in_canonical_scope_and_not_confused_with_qualified_motion():
    """Guide 10's accepted spatial decision must survive the old SLAM exclusion."""
    docs = PLAN.parents[1]
    product = (docs / "product-definition.md").read_text(encoding="utf-8")
    decisions = (docs / "decision-log.md").read_text(encoding="utf-8")
    assert "Accepted first-unit spatial retrieval, 2026-11-23" in product
    assert "first complete robot must find and remember supported objects" in product
    assert "First-unit spatial acceptance in addition to A1–A12" in product
    assert "at least 9/10 reanchors within 20 mm" in product
    assert "at least 8/10 stationary-target returns" in product
    assert "Initial success excludes SLAM, precise map navigation" not in product
    assert "read-only proposal" in product
    assert "No complete delivered checkout quote" in product
    assert "## 2026-11-23 accepted first-unit spatial retrieval" in decisions
    assert "explicitly supersedes the earlier product-brief sentence" in decisions
    parts = {p["id"] for p in load()["parts"]}
    station = {p["id"] for p in load()["room_pod"]["modules"]}
    assert {"xiao_sense", "as5600", "encoder_magnets", "stepper", "uln2003",
            "cliff_obstacle", "i2c_mux", "bumper", "mg90s", "fsr", "ads1115",
            "dock_contacts", "dock_fixture", "cap_power"} <= parts
    assert {"room_controller", "scd40", "bme688", "ld2410c", "soil_probe"} <= station


def test_first_unit_spatial_scope_required_in_machine_plan_without_duplicate_encoder_role():
    """Guide 10 accepted mapping/navigation needs mounting, not phantom new slots."""
    plan = load()
    assert "FIRST complete unit must also find" in plan["fixed_scope"]
    assert "verified wheel displacement" in plan["fixed_scope"]
    assert "one read-only room station shared" in plan["fixed_scope"]
    parts = {x["id"]: x for x in plan["parts"]}
    assert len(parts) == 42
    assert len(plan["room_pod"]["modules"]) == 7
    assert len(plan["linked_subassemblies"]) == 14
    assert parts["as5600"]["per_robot"] == 3
    assert parts["encoder_magnets"]["per_robot"] == 3
    assert "two actual measured wheel-angle/displacement channels" in parts["as5600"]["notes"]
    assert "two physical wheel-encoder brackets" in parts["assembly"]["notes"]
    assert "MUST NOT be charged again" in parts["assembly"]["notes"]
    assert "Require the correct magnet size" in parts["encoder_magnets"]["notes"]
    assert plan["physical_trial_count"] == 0
    assert plan["prices_complete"] is False
