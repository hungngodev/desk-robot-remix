"""Static procurement consistency for the optional haptic effect.

These tests prevent the shop list from implying motor power is qualified merely
because its MCP23017 register source now exists. Actual voltage/current/thermal
and held-high bus tests must still happen on the physical one-shot driver.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FW = ROOT / "code/firmware/body"
HARDWARE = ROOT / "docs/hardware"


def test_haptic_driver_is_one_per_pet_and_not_a_separate_fleet_duplicate():
    plan = json.loads((HARDWARE / "full-feature-plan.json").read_text())
    parts = {part["id"]: part for part in plan["parts"]}
    assert plan["target_robots"] == 5
    for ident in ("haptic_motor", "haptic_driver", "mcp23017"):
        assert parts[ident]["per_robot"] == 1
    assert "CD74HC123" in parts["haptic_driver"]["name"]
    assert "one-shot" in parts["haptic_driver"]["notes"]
    assert "NOT production" in parts["haptic_driver"]["notes"]
    assert "haptic_driver" not in {
        item["id"] for item in plan["linked_subassemblies"]
    }, "The timer, MOSFET and diode are one kit, not a second chargeable line"


def test_haptic_power_never_enabled_implicitly_in_normal_motor_profiles():
    ini = (FW / "platformio.ini").read_text()
    assert "default_envs = esp32_full" in ini
    def section(name):
        label = "[env:" + name + "]"
        assert ini.count(label) == 1
        return ini.split(label, 1)[1].split("\n[env:", 1)[0]
    for env in ("esp32_full", "esp32_dc_full", "esp32_stepper"):
        assert "DESK_ROBOT_ENABLE_HAPTIC=1" not in section(env)
    for env, parent in (("esp32_full_haptic_lab", "esp32_full"),
                        ("esp32_dc_integrated_lab", "esp32_dc_full")):
        lab = section(env)
        assert f"extends = env:{parent}" in lab
        assert "-DDESK_ROBOT_ENABLE_HAPTIC=1" in lab
    assert ini.count("-DDESK_ROBOT_ENABLE_HAPTIC=1") == 2


def test_only_one_owner_of_haptic_output_and_dock_status_precedes_it():
    sources = (FW / "lib/AccessorySensors/AccessorySensors.cpp").read_text()
    head = (FW / "lib/AccessorySensors/AccessorySensors.h").read_text()
    main = (FW / "src/main.cpp").read_text()
    docs = (HARDWARE / "haptic-one-shot-wiring.md").read_text()
    for token in ('write8(0x20, 0x15, 0x00)', 'write8(0x20, 0x01, 0xFB)',
                  'void AccessorySensors::haptic_step', 'haptic_.next'):
        assert token in sources
    case = sources.split("    case 5:", 1)[1].split("    case 6:", 1)[0]
    assert case.index("dock_status(now_ms)") < case.index("haptic_step(now_ms)")
    assert 'haptic_.request(now_ms)' in head
    assert 'control.state().cap_events' in main
    assert 'control.state().touch_raw_active' in main
    assert "CD74HC123" in docs and "GPB0" in docs and "GPB1" in docs
    assert "NOT a buy approval" in docs


def test_generated_robot_harness_matches_live_wiring_emitter():
    import importlib.util

    script = ROOT / "code/scripts/emit_wiring_manifest.py"
    spec = importlib.util.spec_from_file_location("wiring_manifest", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    plan = json.loads((ROOT / module.PLAN).read_text())
    output = module.render(
        plan, (ROOT / module.BODY_PINS).read_text(),
        (ROOT / module.HEAD_PINS).read_text()
    )
    checked_in = (HARDWARE / "one-robot-signal-harness.generated.md").read_text()
    assert output.rstrip() == checked_in.rstrip()
    assert "MCP23017 GPB2" in output
    assert "CD74HC123 rising-edge haptic trigger" in output


def test_amplifier_supply_matches_current_two_watt_speaker():
    """Do not approve a retired 1W speaker on the current 5V output."""
    import copy
    import importlib.util

    import pytest

    path = ROOT / "code/scripts/emit_wiring_manifest.py"
    spec = importlib.util.spec_from_file_location("wiring_audio", path)
    assert spec and spec.loader
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    plan = json.loads((ROOT / generator.PLAN).read_text())
    body = (ROOT / generator.BODY_PINS).read_text()
    head = (ROOT / generator.HEAD_PINS).read_text()
    output = generator.render(plan, body, head)
    assert "Rated, isolated 5V audio power rail" in output
    assert "MAX98357A VDD/VIN" in output
    assert "MAX98357A OUTP and OUTN" in output
    assert "NEVER connect either output to GND" in output
    assert "audio rail peaks, clipping and heat HOLD" in output
    assert output.rstrip() == (HARDWARE /
        "one-robot-signal-harness.generated.md").read_text().rstrip()
    for field, wrong in (
        ("amplifier_vdd_v", 3.3), ("amplifier_vdd_v", True),
        ("speaker_nominal_rating_w", 1),
        ("speaker_nominal_impedance_ohm", 4),
        ("amplifier_ic", "other"),
        ("physical_release", "approved"),
    ):
        corrupt = copy.deepcopy(plan)
        corrupt["audio_output_power_contract"][field] = wrong
        with pytest.raises(ValueError, match="speaker amplifier power contract"):
            generator.verify(corrupt, body, head)


def test_generic_gy530_vin_stays_three_volt_three_and_excludes_5v():
    """Sensor chip and common GY530 level shifted VIN are not 5V host IO."""
    import copy
    import importlib.util

    import pytest

    path = ROOT / "code/scripts/emit_wiring_manifest.py"
    spec = importlib.util.spec_from_file_location("wiring_tof_voltage", path)
    assert spec and spec.loader
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    plan = json.loads((ROOT / generator.PLAN).read_text())
    body = (ROOT / generator.BODY_PINS).read_text()
    head = (ROOT / generator.HEAD_PINS).read_text()
    rendered = generator.render(plan, body, head)
    assert "Rated regulated 3.3V expansion rail" in rendered
    assert "eight GY-530 VL53L0X VIN pins" in rendered
    assert "5V VIN can raise SDA/SCL to 5V" in rendered
    assert rendered.rstrip() == (HARDWARE /
        "one-robot-signal-harness.generated.md").read_text().rstrip()
    voltage = plan["range_breakout_power_contract"]
    assert voltage["exact_vendor_pcb_verified"] is False
    for field, wrong in (
        ("module_vin_v", 5),
        ("module_vin_v", True),
        ("tca9548a_vcc_v", 5),
        ("downstream_pullup_target_v", 5),
        ("upstream_pullup_target_v", 5),
        ("modules_per_robot", 7),
        ("mux_address_7bit", 0x71),
        ("selected_chip", "VL53L4CD"),
    ):
        corrupt = copy.deepcopy(plan)
        corrupt["range_breakout_power_contract"][field] = wrong
        with pytest.raises(ValueError, match="ToF|GY-530"):
            generator.verify(corrupt, body, head)


def test_haptic_wiring_rejects_missing_or_changed_connections():
    """The generated harness must refuse a different or qualified circuit."""
    import copy
    import importlib.util

    import pytest

    path = ROOT / "code/scripts/emit_wiring_manifest.py"
    spec = importlib.util.spec_from_file_location("wiring_haptic", path)
    assert spec and spec.loader
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    plan = json.loads((ROOT / generator.PLAN).read_text())
    body = (ROOT / generator.BODY_PINS).read_text()
    head = (ROOT / generator.HEAD_PINS).read_text()
    rendered = generator.render(plan, body, head)
    for connection in (
        "1B pin 2", "VCC pin 16", "GND pin 8", "1A pin 1 LOW",
        "1CLR pin 3 HIGH", "1Q pin 13", "inverted Q pin 4 unused",
        "1RxCx pin 15", "1Cx pin 14", "AO3400 gate through series resistor",
        "motor negative to AO3400 drain", "AO3400 source",
        "Flyback diode cathode to motor positive, anode to drain",
    ):
        assert connection in rendered
    for field in plan["haptic_output_contract"]:
        corrupt = copy.deepcopy(plan)
        del corrupt["haptic_output_contract"][field]
        with pytest.raises(ValueError, match="haptic one-shot wiring contract"):
            generator.verify(corrupt, body, head)
    for field, wrong in (
        ("logic_supply_v", 5.0), ("trigger_pin", 1), ("trigger_gpio", "GPB1"),
        ("trigger_default", "HIGH"), ("pulse_q_pin", 4),
        ("timing_cx_pin", 15), ("gate_pulldown_required", False),
        ("trigger_pulldown_required", False), ("motor_nominal_v", 5.0),
        ("motor_negative_connection", "expander"), ("flyback_anode_connection", "motor_positive"),
        ("flyback_cathode_connection", "mosfet_drain"),
        ("physical_qualified", True), ("physical_release", "APPROVED"),
    ):
        corrupt = copy.deepcopy(plan)
        corrupt["haptic_output_contract"][field] = wrong
        with pytest.raises(ValueError, match="haptic one-shot wiring contract"):
            generator.verify(corrupt, body, head)
