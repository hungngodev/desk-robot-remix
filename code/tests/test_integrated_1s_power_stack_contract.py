"""Stop a half integrated charger, battery, dock, WROOM, or Mac receipt.

This contract checks real source identity. It does not verify physical copper,
fuse performance, assembly, PCM trip thresholds or charge authorization.
"""
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "code"
HW = ROOT / "docs/hardware"


def test_single_mathematical_owner_joins_all_five_power_domains():
    math = (SRC / "scripts/power_preflight.py").read_text()
    for source in (
        "def screen_one_cell_power_stack(",
        "size_5v_supply(",
        "screen_protected_pack(",
        "screen_bq2407x_output_path(",
        "assess_docked_load(",
        "charger_ts_is_connected_to_actual_pack_ntc",
        "charger_out_to_regulated_5v_covers_3v_cell_and_dock",
        "docked_idle_plus_cell_charge_in_same_1_5a_budget",
        '"qualified_1s_dock_safe_to_buy": False',
        '"all_power_stages_physically_verified": False',
    ):
        assert source in math
    tests = (SRC / "tests/test_power_preflight.py").read_text()
    for case in (
        "test_complete_one_cell_stack_proves_only_math_not_battery_safety",
        "test_stack_rejects_wrong_regulator_only_rated_at_five_volts",
        "test_stack_rejects_5v_only_regulator_on_bq24075_dock",
        "test_stack_does_not_ignore_actual_ntc_jumper_and_connector",
        "test_stack_will_not_count_1_5a_bq24075_twice",
        "test_stack_requires_disarmed_motors_and_actual_pack_volume",
        "test_known_undersized_rating_rejects_pack_even_when_other_ratings_missing",
        "test_integrated_stack_respects_charger_bat_and_out_operating_limit",
    ):
        assert case in tests


def test_actual_ina226_measurement_is_one_fresh_owner_with_an_opt_in_build():
    readings = (SRC / "firmware/body/lib/AccessorySensors/AccessoryReadings.h").read_text()
    bus = (SRC / "firmware/body/lib/AccessorySensors/AccessorySensors.cpp").read_text()
    body = (SRC / "firmware/body/lib/BodyControl/BodyControl.cpp").read_text()
    ini = (SRC / "firmware/body/platformio.ini").read_text()
    for token in ("ina226_pack_current_ma(", "shunt_milliohm != 5U",
                  "pack_current_ma", "pack_current_valid",
                  "monitor_sample_seq"):
        assert token in readings
    for token in ("DESK_ROBOT_PACK_SHUNT_MOHM", "monitor_sample_seq",
                  "g.pack_current_valid = ina226_pack_current_ma",
                  "g.pack_current_valid = false"):
        assert token in bus
    # Source-level wire format check: C++ string literals escape every
    # embedded quote, so look for the field and its actual printf format,
    # not an extra unmatched opening C++ string delimiter.
    for token in (r'pack_ma\":%d', r'pack_valid\":%s',
                  r'pack_seq\":%lu'):
        assert token in body
    assert ini.count("-DDESK_ROBOT_PACK_SHUNT_MOHM=5") == 1
    assert "[env:esp32_dc_integrated_lab]" in ini
    assert "DESK_ROBOT_PACK_SHUNT_MOHM=5" not in ini.split(
        "[env:esp32_dc_integrated_lab]", 1)[0]


def test_mac_does_not_equate_chg_status_pin_with_net_battery_charge():
    dock = (SRC / "laptop/src/desk_robot/dock_evidence.py").read_text()
    parser = (SRC / "laptop/src/desk_robot/aux.py").read_text()
    tests = (SRC / "tests/test_dock_evidence.py").read_text()
    for needle in ("raw_pack_samples", "raw_pack_samples_fresh",
                   "raw_pack_direction", "acquisition_replay",
                   "charger_indicator_net_discharge_conflict"):
        assert needle in dock
    assert '"battery_current_measured": False' in dock
    assert '"charging_verified": False' in dock
    assert '"charging_authorized": False' in dock
    # The optional signed-current fields are first checked for completeness,
    # then indexed only after that gate. Requiring .get here was a stale
    # textual test and would weaken the established complete-record check.
    for needle in ('power["pack_valid"]', '"pack_seq"',
                   'power["pack_ma"] != int(power["shunt_uv"] / 5)'):
        assert needle in parser
    assert "test_raw_pack_replay_cannot_forge_three_current_conversions" in tests
    assert "test_new_ina226_current_receipts_report_direction" in tests


def test_wiring_generator_and_checked_in_harness_match_charger_pins():
    source = (SRC / "scripts/emit_wiring_manifest.py").read_text()
    generated = (HW / "one-robot-signal-harness.generated.md").read_text()
    rows = [
        "BQ24075 IN pin 13 with local bypass",
        "BQ24075 OUT pins 10/11: battery-dependent 3V to 5.6V",
        "BQ24075 BAT pins 2/3, through 5mOhm >=2W Kelvin shunt",
        "Charger VSS and TS pin 1 respectively",
        "INA226 0x40 on accessory TCA9548A 0x71 CH4",
        "MCP23017 0x20 GPA2/GPA3 via 3.3V pullups",
    ]
    for row in rows:
        assert row in source
        assert row in generated
    note = (HW / "2026-11-17-one-pet-protected-power-circuit.md").read_text()
    for gate in ("TS 1", "BAT 2,3", "OUT 10,11", "IN 13",
                 "PGOOD 7", "CHG 9", "ILIM 12", "VSS 8", "ISET 16"):
        assert gate in note
    assert "THIS IS A POWER SCHEMATIC" in note


def test_all_exact_battery_candidates_are_screened_but_none_order_released():
    catalog = (SRC / "scripts/screen_vendor_battery_harness.py").read_text()
    docs = (HW / "2026-11-17-protected-pack-and-connector-audit.md").read_text()
    for model in ("LP103650", "LPHD7430085", "PR-CU-R512-22AWG",
                  "PR-CU-R512-JST-SHR", "PR-CU-R512-Molex-26AWG",
                  "VARTA-VAR56653502013", "LITECH-LP1S2P2A2AL005",
                  "BATTERYSPACE-CU-JAS427", "THOR-18650-1S2P-5200",
                  "NX-MGL00850-1S2P"):
        assert model in catalog
    assert '"complete_power_path_safe_to_buy": False' in catalog
    assert "TEN exact manufacturer configurations" in docs
    assert 'fit = None' in catalog


def test_full_body_power_monitor_and_cutoff_are_wired_to_compiled_profiles():
    """Source and builder contract only, not a physical qualification."""
    ini = (SRC / "firmware/body/platformio.ini").read_text()
    main = (SRC / "firmware/body/src/main.cpp").read_text()
    control = (SRC / "firmware/body/lib/BodyControl/BodyControl.cpp").read_text()
    header = (SRC / "firmware/body/lib/BodyControl/BodyControl.h").read_text()
    guarded = (SRC / "firmware/body/tests/guarded_body_tests.cpp").read_text()
    wiring = (HW / "wiring.md").read_text()
    assert ini.count("-DDESK_ROBOT_REQUIRE_FUEL_MONITOR=1") == 2
    assert "[env:esp32_full]" in ini
    assert "[env:esp32_dc_full]" in ini
    assert "-DDESK_ROBOT_STEPPER_HARDWARE_CUTOFF_QUALIFIED=0" in ini
    assert "control.require_fuel_monitor(true)" in main
    assert "control.inhibit_unqualified_motor_cutoff()" in main
    assert "fuel_monitor_fresh(now_ms)" in control
    assert "ERR arm fuel_monitor_latched" in control
    assert "ERR arm motor_cutoff_unqualified" in control
    assert "void inhibit_unqualified_motor_cutoff();" in header
    assert "required_fuel_gauge_loss_stops_and_requires_local_rearm" in guarded
    assert "unqualified_stepper_cutoff_never_claims_motion_ready" in guarded
    assert "DESK_ROBOT_REQUIRE_FUEL_MONITOR=1" in wiring
    assert "motor_cutoff_unqualified" in wiring
    assert "physically qualified" in wiring


@pytest.mark.parametrize("variant", ["BQ24074", "BQ24075"])
@pytest.mark.parametrize("effective_min_v, expected", [
    (2.8, True), (2.9, True), (2.901, False), (3.0, False), (3.4, False),
])
def test_bq2407x_output_path_reserves_battery_dropout_headroom(
    variant, effective_min_v, expected
):
    # Pololu #2873 has a 3 V cutoff and 3.4 V restart threshold.
    # Its raw 2 V operating rating is not its effective minimum.
    screen = runpy.run_path(str(SRC / "scripts/power_preflight.py"))[
        "screen_bq2407x_output_path"
    ]
    result = screen(
        variant, regulator_min_input_v=effective_min_v,
        regulator_max_input_v=16, regulator_topology="buck_boost",
    )
    assert result["regulator_covers_charger_output_on_paper"] is expected
    assert result["charger_and_5v_rail_physically_qualified"] is False
