"""Keep shared hardware guards enabled in every full drivetrain image."""

import shlex
import shutil
import subprocess
from configparser import ConfigParser
from pathlib import Path

import pytest

BODY = Path(__file__).resolve().parents[1] / "firmware" / "body"
FULL_GUARDS = (
    "EXTRA_RANGERS",
    "REQUIRE_DOCK_MONITOR",
    "REQUIRE_FUEL_MONITOR",
    "ENABLE_BUMPER",
    "ENABLE_TERMINAL_IR",
    "ENABLE_REED",
)


def _config():
    config = ConfigParser(interpolation=None)
    config.read_string((BODY / "platformio.ini").read_text(encoding="utf-8"))
    return config


def _flags(config, section):
    for token in shlex.split(config[section]["build_flags"]):
        if token.startswith("${") and token.endswith(".build_flags}"):
            yield from _flags(config, token[2:-len(".build_flags}")])
        else:
            yield token


def _defines(config, section):
    definitions = {}
    for token in _flags(config, section):
        if token.startswith("-DDESK_ROBOT_"):
            name, _, value = token[len("-DDESK_ROBOT_"):].partition("=")
            assert name not in definitions or definitions[name] == value, (section, name)
            definitions[name] = value
    return definitions


@pytest.mark.parametrize("section", [
    "env:esp32_full",
    "env:esp32_full_pulse_reversed_lab",
    "env:esp32_full_interaction_lab",
    "env:esp32_full_haptic_lab",
    "env:esp32_dc_full",
    "env:esp32_dc_watchdog_lab",
    "env:esp32_dc_integrated_lab",
])
def test_full_drivetrain_profiles_keep_shared_safety(section):
    config = _config()
    flags = _defines(config, section)
    stepper = "0" if section.startswith("env:esp32_dc_") else "1"
    assert flags["STEPPER"] == stepper
    # main.cpp defaults FULL_SENSORS to STEPPER when not explicitly defined.
    assert flags.get("FULL_SENSORS", stepper) == "1"
    for guard in FULL_GUARDS:
        assert flags.get(guard) == "1", (section, guard)
    for backend in ("DC", "STEPPER"):
        assert flags.get(f"{backend}_HARDWARE_CUTOFF_QUALIFIED", "0") == "0"
    assert flags.get("ENABLE_DC_WATCHDOG", "0") == ("0" if stepper == "1" else "1")
    assert flags.get("REQUIRE_DC_NFAULT", "0") == ("0" if stepper == "1" else "1")


def test_all_environments_classified_and_bench_sources_isolated():
    config = _config()
    expected = {
        "esp32_full", "esp32_full_pulse_reversed_lab", "esp32_full_interaction_lab",
        "esp32_full_haptic_lab", "esp32_dc_full", "esp32_dc_watchdog_lab",
        "esp32_dc_integrated_lab", "esp32dev", "esp32_stepper",
        "esp32_servo_center_bench", "esp32_vl53l0x_bench",
    }
    assert {s[4:] for s in config.sections() if s.startswith("env:")} == expected
    assert config["platformio"]["default_envs"] == "esp32_full"
    assert set(config["env"]["build_src_filter"].split()) == {
        "+<*>", "-<vl53l0x_bench.cpp>", "-<servo_center_bench.cpp>",
    }
    for name, source in (("servo_center", "servo_center"), ("vl53l0x", "vl53l0x")):
        section = f"env:esp32_{name}_bench"
        assert set(config[section]["build_src_filter"].split()) == {
            "-<*>", f"+<{source}_bench.cpp>",
        }
    for name in ("esp32dev", "esp32_servo_center_bench"):
        flags = _defines(config, f"env:{name}")
        assert flags["STEPPER"] == flags["FULL_SENSORS"] == "0"
    for name in ("esp32_stepper", "esp32_vl53l0x_bench"):
        flags = _defines(config, f"env:{name}")
        assert flags["STEPPER"] == "1"
        assert flags.get("STEPPER_HARDWARE_CUTOFF_QUALIFIED", "0") == "0"


def test_pin_header_compiles_under_every_environment():
    """Compile actual GPIO ownership assertions with the resolved profile flags."""
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("C++ compiler unavailable for pin matrix")
    config = _config()
    source = r'''
#include "BodyPins.h"
using namespace body_pins;
static_assert(kUartRx == 16 && kUartTx == 17);
static_assert(kLiftServo == 18 && kGripServo == 19);
#if DESK_ROBOT_STEPPER || DESK_ROBOT_FULL_SENSORS
static_assert(kSensorSda == 21 && kSensorScl == 22);
static_assert(kTouchOutput == 34 && kBumperInput == 35);
static_assert(kTerminalIrLeftInput == 36 && kTerminalIrRightInput == 39);
#endif
#if DESK_ROBOT_STEPPER
static_assert(kRightStepperPins[3] == 23 && count(kMotorPins) == 8);
#elif DESK_ROBOT_ENABLE_DC_WATCHDOG
static_assert(kDcHeartbeatPin == 23 && count(kMotorPins) == 4);
#endif
int main() { return 0; }
'''
    for section in config.sections():
        if not section.startswith("env:"):
            continue
        result = subprocess.run(
            [compiler, "-std=c++17", "-Werror", "-fsyntax-only",
             "-I", str(BODY / "include"), *_flags(config, section), "-x", "c++", "-"],
            input=source, text=True, capture_output=True, check=False, timeout=10,
        )
        assert result.returncode == 0, (section, result.stderr)
