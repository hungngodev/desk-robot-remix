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
