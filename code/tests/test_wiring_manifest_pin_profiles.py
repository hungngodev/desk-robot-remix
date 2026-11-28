"""Firmware profile and signal allocation regressions for the wiring generator."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "emit_wiring_manifest", ROOT / "code/scripts/emit_wiring_manifest.py"
)
assert SPEC is not None and SPEC.loader is not None
manifest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manifest)


@pytest.fixture
def pins_and_source():
    plan = json.loads((ROOT / "docs/hardware/full-feature-plan.json").read_text())
    body = (ROOT / "code/firmware/body/include/BodyPins.h").read_text()
    return plan["bus"]["body_gpio"], body


def test_full_body_profiles(pins_and_source):
    pins, body = pins_and_source
    manifest._verify_gpio_map("body_gpio", pins)
    manifest._verify_body_profiles(pins, body)


def test_multiline_pin_initializers_and_guard(pins_and_source):
    pins, body = pins_and_source
    body = body.replace("{13, 14, 25, 26}", "{\n13, /* phase */ 14,\n25, 26,\n}")
    body = body.replace("{kLiftServo, kGripServo}", "{\nkLiftServo,\n kGripServo,\n}")
    body = body.replace("#if DESK_ROBOT_STEPPER || (", "#if DESK_ROBOT_STEPPER || \\\n(")
    manifest._verify_body_profiles(pins, body)


def test_inactive_and_commented_declarations_are_not_pins(pins_and_source):
    pins, body = pins_and_source
    body = body.replace(
        "constexpr int kLiftServo = 18;",
        "#if 0\nconstexpr int kLiftServo = 19;\n#endif\n"
        "/* constexpr int kLiftServo = 19; */\nconstexpr int kLiftServo = 18;",
    )
    manifest._verify_body_profiles(pins, body)


@pytest.mark.parametrize("guard", ["#if 0", "#ifdef DESK_ROBOT_ENABLE_DC_WATCHDOG"])
def test_missing_active_pin_cannot_be_proven_by_inactive_declaration(pins_and_source, guard):
    pins, body = pins_and_source
    body = body.replace(
        "constexpr int kLiftServo = 18;", f"{guard}\nconstexpr int kLiftServo = 18;\n#endif"
    )
    with pytest.raises(ValueError, match="kLiftServo"):
        manifest._verify_body_profiles(pins, body)


def test_wrong_dc_guard(pins_and_source):
    pins, body = pins_and_source
    body = body.replace("#if !DESK_ROBOT_STEPPER", "#if DESK_ROBOT_STEPPER")
    with pytest.raises(ValueError):
        manifest._verify_body_profiles(pins, body)


def test_duplicate_active_symbol(pins_and_source):
    pins, body = pins_and_source
    body = body.replace(
        "constexpr int kLiftServo = 18;",
        "constexpr int kLiftServo = 18;\nconstexpr int kLiftServo = 18;",
    )
    with pytest.raises(ValueError, match="duplicate firmware pin: kLiftServo"):
        manifest._verify_body_profiles(pins, body)


def test_duplicate_gpio_in_synchronized_stepper_map(pins_and_source):
    pins, body = pins_and_source
    pins["left_stepper"][1] = pins["left_stepper"][0]
    body = body.replace("{13, 14, 25, 26}", "{13, 13, 25, 26}")
    manifest._verify_body_profiles(pins, body)
    with pytest.raises(ValueError, match="Double-booked body_gpio GPIO"):
        manifest._verify_gpio_map("body_gpio", pins)


def test_stepper_remap_does_not_hide_dc_servo_collision(pins_and_source):
    pins, body = pins_and_source
    pins["left_stepper"][2] = 18
    pins["lift_servo"] = 25
    body = body.replace("{13, 14, 25, 26}", "{13, 14, 18, 26}")
    body = body.replace("constexpr int kLiftServo = 18;", "constexpr int kLiftServo = 25;")
    manifest._verify_gpio_map("body_gpio", pins)
    with pytest.raises(ValueError, match="DC profile GPIO collides"):
        manifest._verify_body_profiles(pins, body)


def test_unknown_build_flag_fails_closed(pins_and_source):
    pins, body = pins_and_source
    body = body.replace(
        "constexpr int kLiftServo = 18;",
        "#ifdef UNKNOWN_PROFILE\nconstexpr int kLiftServo = 18;\n#endif",
    )
    with pytest.raises(ValueError, match="Unknown BodyPins build flag"):
        manifest._verify_body_profiles(pins, body)
