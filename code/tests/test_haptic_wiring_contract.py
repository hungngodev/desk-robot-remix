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
    lab = section("esp32_full_haptic_lab")
    assert "extends = env:esp32_full" in lab
    assert "-DDESK_ROBOT_ENABLE_HAPTIC=1" in lab


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
