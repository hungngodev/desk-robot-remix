"""All 63 engineering decisions must have an actual owner and test path.

Source presence != passing tests, physical fit, valid electrical drawing or
purchasing approval. This is a traceability contract that cannot reduce scope.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HARDWARE = ROOT / "docs/hardware"


def _sources():
    plan = json.loads((HARDWARE / "full-feature-plan.json").read_text())
    owner = json.loads((HARDWARE / "full-63-role-source-ownership.json").read_text())
    return plan, owner


VALID_SOURCE_STATES = frozenset({
    "adc_driver_source", "alternate_dc_firmware_only", "angle_driver_source",
    "boost_paper_screen_only", "cad_scaffold_not_assembly", "charger_paper_screen_only",
    "closed_loop_host_source", "dock_adapter_paper_screen_only",
    "dock_beacon_firmware_source", "dock_driver_source_only", "dock_gpio_haptic_source",
    "environment_driver_source", "exclusive_legacy_motor_source",
    "external_hardware_timing_unverified", "full_profile_soil_source",
    "head_camera_mic_firmware", "head_display_firmware", "host_nfc_game_logic_source",
    "identity_and_readonly_source", "local_guarded_ranger_source",
    "local_motor_safety_source", "local_nc_bumper_source", "local_touch_stop_source",
    "native_i2s_audio_source", "nfc_host_logic_source", "opt_in_haptic_source",
    "opt_in_rgb_source", "optical_raw_source", "optional_gesture_source",
    "optional_gpio_read_source", "pack_paper_screen_only", "passive_bom_geometry_only",
    "passive_dock_adapter_only", "physical_electronics_only",
    "power_calculator_not_schematic", "power_harness_signal_only",
    "read_only_dual_nec_source", "read_only_nfc_source",
    "readonly_contact_detection_only", "readonly_fuel_source",
    "readonly_power_telemetry_source", "servo_output_source",
    "shared_feather_firmware_only", "speaker_fit_reference_only",
    "station_read_only_source", "station_soil_source", "station_thermal_source",
    "station_usb_source", "touch_driver_source", "two_mux_source",
})

ROLE_EVIDENCE_MARKERS = {
    ("pet_roles", "pn532"): (("PN532", "pn532"), ("pn532", "NfcRaw")),
    ("pet_roles", "oled"): (("SSD1306", "Oled", "Display"), ("oled", "SSD1306", "sense")),
    ("pet_roles", "xiao_sense"): (("robot_bridge", "CAMERA"), ("sense", "camera")),
    ("pet_roles", "imu"): (("IMU", "MPU6050", "BerryImu"), ("imu", "probe_imu")),
    ("pet_roles", "i2c_mux"): (("TCA9548A", "TofBus"), ("mux", "tof")),
    ("pet_roles", "cliff_obstacle"): (("VL53L0X", "TofBus"), ("cliff", "tof")),
}


def _validate_ownership_matrix(plan, owners):
    assert len(plan["parts"]) == 42
    assert len(plan["room_pod"]["modules"]) == 7
    assert len(plan["linked_subassemblies"]) == 14
    non_code_sources = {
        ("pet_roles", "speaker"): "docs/cad/remixes/speaker_rect_fit_gauge.scad",
        ("pet_roles", "touch_electrodes"): "docs/cad/remixes/one_robot_adapter_kit.scad",
        ("pet_roles", "encoder_magnets"): "docs/cad/remixes/one_robot_adapter_kit.scad",
        ("pet_roles", "haptic_driver"): "docs/hardware/haptic-one-shot-wiring.md",
        ("pet_roles", "dock_fixture"): "docs/cad/remixes/dock/dock_passive_fit.scad",
        ("pet_roles", "assembly"): "docs/cad/remixes/fusion_assembly_scaffold.py",
        ("linked_roles", "drv8833_driver_candidate"): "docs/hardware/dc-motor-independent-watchdog.md",
    }
    for section, entries in (
        ("pet_roles", plan["parts"]),
        ("room_roles", plan["room_pod"]["modules"]),
        ("linked_roles", plan["linked_subassemblies"]),
    ):
        ids = [part["id"] for part in entries]
        assert len(ids) == len(set(ids))
        assert set(owners[section]) == set(ids), (
            section, set(ids) ^ set(owners[section]))
        for id_, row in owners[section].items():
            assert isinstance(row["source_state"], str) and row["source_state"]
            assert row["source_state"] in VALID_SOURCE_STATES, (id_, row["source_state"])
            assert isinstance(row["remaining_qualification"], str)
            assert len(row["remaining_qualification"]) >= 12, id_
            texts = {}
            for key in ("source", "host_test"):
                path = row[key]
                assert isinstance(path, str)
                if key == "host_test":
                    assert path.startswith("code/") and "/tests/" in path, (id_, path)
                elif (section, id_) in non_code_sources:
                    assert path == non_code_sources[(section, id_)], (id_, path)
                else:
                    assert path.startswith("code/"), (id_, path)
                actual = (ROOT / path).resolve()
                assert actual.is_relative_to(ROOT.resolve()), id_
                assert actual.is_file(), (id_, key, path)
                assert actual.stat().st_size > 40, (id_, key, path)
                texts[key] = actual.read_text(encoding="utf-8")
            markers = ROLE_EVIDENCE_MARKERS.get((section, id_))
            if markers is not None:
                src_tokens, test_tokens = markers
                assert any(tok in texts["source"] for tok in src_tokens), (id_, row["source"])
                assert any(tok in texts["host_test"] for tok in test_tokens), (id_, row["host_test"])
    pet_ids = {item["id"] for item in plan["parts"]}
    room_ids = {item["id"] for item in plan["room_pod"]["modules"]}
    for linked in plan["linked_subassemblies"]:
        assert linked["parent_role"] in pet_ids | room_ids


def test_all_physical_roles_and_linked_decisions_have_exact_source_owners():
    plan, owners = _sources()
    _validate_ownership_matrix(plan, owners)


def test_ownership_matrix_rejects_cross_role_substitution_and_unapproved_states():
    import copy

    import pytest

    plan, owners = _sources()
    swapped = copy.deepcopy(owners)
    swapped["pet_roles"]["pn532"]["source"] = "code/firmware/head/sense/desk_robot_sense.cc"
    swapped["pet_roles"]["pn532"]["host_test"] = "code/firmware/head/tests/test_sense.py"
    with pytest.raises(AssertionError):
        _validate_ownership_matrix(plan, swapped)

    bad_state = copy.deepcopy(owners)
    bad_state["pet_roles"]["pn532"]["source_state"] = "ready_for_purchase"
    with pytest.raises(AssertionError):
        _validate_ownership_matrix(plan, bad_state)


def test_ownership_matrix_never_equates_source_presence_with_buy_approval():
    plan, owners = _sources()
    assert plan["target_robots"] == 5
    assert plan["qualified_assumptions"] is False
    assert plan["physical_trial_count"] == 0
    assert plan["prices_complete"] is False
    assert "physical" in owners["description"]
    for section in ("pet_roles", "room_roles", "linked_roles"):
        for role, entry in owners[section].items():
            assert entry["source_state"] != "production_qualified", role
            assert entry["source_state"] != "safe_to_purchase", role
            assert "remaining_qualification" in entry


def test_unbuilt_power_and_dock_are_not_hidden_by_existing_driver_code():
    _, owners = _sources()
    for key in ("cap_power", "sensor_3v3", "switch_power"):
        assert "power" in owners["pet_roles"][key]["source_state"]
    assert owners["pet_roles"]["dock_contacts"]["source_state"] == (
        "readonly_contact_detection_only")
    assert owners["pet_roles"]["assembly"]["source_state"] == (
        "cad_scaffold_not_assembly")
    assert owners["linked_roles"]["protected_ntc_pack"]["source_state"] == (
        "pack_paper_screen_only")


def test_procurement_still_gates_every_physical_feature():
    release = (ROOT / "code/scripts/procurement_release.py").read_text()
    for gate in ("protected_1s_charger_and_dock_contacts",
                 "battery_pack_ntc_to_charger_ts_thermal_fault_trial",
                 "hardware_motor_driver_fails_low_after_cpu_stall",
                 "four_floor_sensor_reverse_pivot_arc_sweep",
                 "cliff_sensor_mount_height_and_stopping_geometry",
                 "real_dual_ir_terminal_docking",
                 "sense_speaker_mic_double_talk",
                 "five_robot_integration",
                 "user_approved_costed_exact_carrier_bill_of_materials"):
        assert f'"{gate}"' in release


def test_max30102_compiled_fifo_layout_is_disclosed_not_qualified():
    """A lab firmware variant must disclose orientation without claiming proof."""
    body = (ROOT / "code/firmware/body/lib/BodyControl/BodyControl.cpp").read_text()
    platformio = (ROOT / "code/firmware/body/platformio.ini").read_text()
    native = (ROOT / "code/firmware/body/tests/guarded_body_tests.cpp").read_text()
    assert "DESK_ROBOT_MAX30102_FIFO_IR_FIRST" in body
    assert "kPulseIrFirstJson" in body
    assert r'"fifo_ir_first":%s' not in body  # C++ source uses escaped JSON keys
    assert r'\"fifo_ir_first\":%s' in body
    assert r'\"fifo_layout_physically_verified\":false' in body
    assert "DESK_ROBOT_MAX30102_FIFO_IR_FIRST=1" in platformio
    assert r'\"fifo_ir_first\":false' in native
    assert r'\"fifo_layout_physically_verified\":false' in native
    assert "esp32_full_pulse_reversed_lab" in (
        ROOT / ".github/workflows/host-verification.yml"
    ).read_text()


def test_imu_role_tracks_selected_mpu6050_without_physical_qualification():
    plan, owners = _sources()
    selected = next(part for part in plan["parts"] if part["id"] == "imu")
    assert selected["per_robot"] == 1
    assert "MPU6050" in selected["name"]
    assert "BerryIMU preserved as spare" in selected["notes"]
    owner = owners["pet_roles"]["imu"]
    assert owner["source"] == "code/firmware/body/lib/BerryImu/BerryImu.cpp"
    assert owner["host_test"] == "code/firmware/body/tests/berry_imu_tests.cpp"
    assert owner["source_state"] == "identity_and_readonly_source"
    assert "orientation calibration" in owner["remaining_qualification"]


EXPANSION_SENSOR_LAYOUT = {
    "max30102": ("0", "0x57"),
    "apds9960": ("1", "0x39"),
    "sht41": ("3", "0x44"),
    "bmp280": ("3", "0x76 / 0x77"),
    "mcp23017": ("5", "0x20"),
    "pn532": ("5", "0x24"),
}


def _validate_expansion_sensor_rows(doc, plan, owners):
    section = doc.split("## Selected expansion sensor roles\n", 1)[1]
    section = section.split("\n## ", 1)[0]
    rows = {}
    for line in section.splitlines():
        if not line.startswith("| `"):
            continue
        role, lane, address, state, _ = (cell.strip() for cell in line.split("|")[1:-1])
        role = role.strip("`")
        assert role not in rows, role
        rows[role] = (lane, address, state.strip("`"))
    assert set(rows) == set(EXPANSION_SENSOR_LAYOUT)
    quantities = {part["id"]: part["per_robot"] for part in plan["parts"]}
    for role, (lane, address) in EXPANSION_SENSOR_LAYOUT.items():
        assert quantities[role] == 1, role
        assert rows[role] == (lane, address, owners["pet_roles"][role]["source_state"]), role


def test_expansion_sensor_doc_tracks_selected_layout_and_ownership():
    plan, owners = _sources()
    doc = (HARDWARE / "interaction-sensors.md").read_text()
    _validate_expansion_sensor_rows(doc, plan, owners)


def test_expansion_sensor_doc_rejects_lane_address_and_state_drift():
    import pytest

    plan, owners = _sources()
    doc = (HARDWARE / "interaction-sensors.md").read_text()
    for old, new in (
        ("`pn532` | 5 |", "`pn532` | 6 |"),
        ("`dock_gpio_haptic_source`", "`production_qualified`"),
        ("`bmp280` | 3 | 0x76 / 0x77", "`bmp280` | 3 | 0x76"),
    ):
        assert old in doc
        with pytest.raises(AssertionError):
            _validate_expansion_sensor_rows(doc.replace(old, new), plan, owners)


# The archived quote uses descriptions rather than role IDs. Keep an explicit
# crosswalk: kit rows may cover several roles, and several rows may share one
# role. Neither case grants additional purchasing authority.
ARCHIVED_BOM_ROWS = {
    "Purchased XIAO ESP32S3 Sense camera/PDM microphone bundle "
    "(physical identity and condition to inspect)": (1, ("xiao_sense",)),
    "MAX98357 I2S amplifier breakout, ElectroPeak SEN-17-139": (1, ("amp",)),
    "8 ohm 1 W speaker, 20 mm x 3.75 mm, ElectroPeak SEN-17-105": (1, ("speaker",)),
    "TCA9548A eight-channel I2C multiplexer breakout": (1, ("i2c_mux",)),
    "Owned ESP32-WROOM-32 dev board": (1, ("wroom",)),
    "Owned 0.96 inch four-pin SSD1306 OLED, GME12864-11": (1, ("oled",)),
    "Owned 5 V 28BYJ-48 stepper motor": (2, ("stepper",)),
    "Owned ULN2003 stepper driver board": (2, ("uln2003",)),
    "Reported MG90S positional micro servo, about 10 owned (user estimate)": (2, ("mg90s",)),
    "Owned filament": (1, ("assembly",)),
    "Owned DuPont signal wire ribbons": (1, ("assembly",)),
    "Rated actuator power lead, switch, connectors, fasteners and wiring": (
        1, ("assembly", "switch_power")),
    "Bulk and local decoupling components": (1, ("switch_power", "sensor_3v3")),
    "VL53L0X GY-530 generic downward cliff carriers, exact sample unqualified": (
        4, ("cliff_obstacle",)),
    "VL53L0X GY-530 generic forward obstacle carrier, exact sample unqualified": (
        1, ("cliff_obstacle",)),
    "VL53L0X GY-530 generic side and rear observation carriers, exact sample unqualified": (
        3, ("cliff_obstacle",)),
    "Owned Adafruit AT42QT1010 momentary touch breakout #1374": (1, ("head_touch",)),
    "User-reported MPU6050 six-axis module for prototype "
    "(quantity and breakout to verify)": (1, ("imu",)),
    "Matched rechargeable1S cell/holder charging-protection-5V kit": (1, ("cap_power",)),
}
ARCHIVED_OPTIONAL_ROWS = {
    "One diffused RGB pixel plus level buffer and passives": (1, ("rgb", "logic_level")),
    "Mechanical bumper switch plus external pullup": (1, ("bumper",)),
    "Conditional generic MPU6050 GY-521 replacement ONLY if existing MPU6050 "
    "and BerryIMU both fail testing": (1, ("imu",)),
}


def _validate_archived_bom(bom, owners):
    assert bom["historical_prototype_only"] is True
    assert bom["procurement_authority"] is False
    assert bom["superseded_by"] == "docs/hardware/full-feature-plan.json"
    for section, expected in (("items", ARCHIVED_BOM_ROWS),
                              ("optional_items", ARCHIVED_OPTIONAL_ROWS)):
        rows = bom[section]
        names = [row["item"] for row in rows]
        assert len(names) == len(set(names)), section
        assert set(names) == set(expected), (section, set(names) ^ set(expected))
        for row in rows:
            quantity, roles = expected[row["item"]]
            assert type(row["quantity"]) is int and row["quantity"] == quantity, row["item"]
            assert set(roles) <= owners["pet_roles"].keys(), (row["item"], roles)


def test_archived_bom_rows_have_explicit_owners_without_purchase_authority():
    _, owners = _sources()
    bom = json.loads((HARDWARE / "bom.json").read_text())
    _validate_archived_bom(bom, owners)


def test_archived_bom_rejects_unmapped_duplicate_and_unowned_parts():
    import copy

    import pytest

    _, owners = _sources()
    bom = json.loads((HARDWARE / "bom.json").read_text())
    for section in ("items", "optional_items"):
        for mutation in ("unknown", "duplicate", "missing", "quantity", "boolean"):
            altered = copy.deepcopy(bom)
            rows = altered[section]
            if mutation == "unknown":
                rows.append({"item": "Unmapped fastener", "quantity": 1})
            elif mutation == "duplicate":
                rows.append(rows[0].copy())
            elif mutation == "missing":
                rows.pop()
            elif mutation == "quantity":
                rows[0]["quantity"] += 1
            else:
                rows[0]["quantity"] = True
            with pytest.raises(AssertionError):
                _validate_archived_bom(altered, owners)
    for role in ("assembly", "switch_power", "sensor_3v3"):
        altered_owners = copy.deepcopy(owners)
        del altered_owners["pet_roles"][role]
        with pytest.raises(AssertionError):
            _validate_archived_bom(bom, altered_owners)
    altered = dict(bom, procurement_authority=True)
    with pytest.raises(AssertionError):
        _validate_archived_bom(altered, owners)


def test_current_plan_keeps_passive_kits_and_fleet_counts_separate_from_archive():
    plan, _ = _sources()
    assert plan["target_robots"] == 5
    pet = {part["id"]: part["per_robot"] for part in plan["parts"]}
    room = {part["id"]: part["quantity_per_room"] for part in plan["room_pod"]["modules"]}
    # These are design slots, not counts of individual screws or wires.
    expected = {
        "assembly": 1, "switch_power": 1, "sensor_3v3": 1, "cap_power": 1,
        "cliff_obstacle": 8, "i2c_mux": 2, "bumper": 2, "dock_fixture": 1,
        "as5600": 3, "encoder_magnets": 3, "xiao_sense": 1, "amp": 1,
        "speaker": 1, "wroom": 1, "oled": 1, "stepper": 2, "uln2003": 2,
        "mg90s": 2, "head_touch": 1, "imu": 1, "rgb": 1, "logic_level": 1,
    }
    assert all(type(pet[role]) is int and pet[role] == qty for role, qty in expected.items())
    for decision in plan["linked_subassemblies"]:
        parent = decision["parent_role"]
        count = decision["fleet_quantity"]
        assert type(count) is int and count > 0, decision["id"]
        if parent in room:
            assert count == room[parent], decision["id"]
        else:
            # A dual H bridge replaces two single motor driver boards.
            per_robot = 1 if decision["id"] == "drv8833_driver_candidate" else pet[parent]
            assert count == per_robot * plan["target_robots"], decision["id"]
    assert room["room_controller"] == 1
