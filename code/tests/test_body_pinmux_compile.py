"""Compile the WROOM pin contract and reject deliberately corrupted allocations."""
import configparser
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

HEADER = Path(__file__).resolve().parents[1] / "firmware/body/include/BodyPins.h"
COMPILER = shutil.which("g++")
pytestmark = pytest.mark.skipif(COMPILER is None, reason="g++ is unavailable")


def compile_header(source, flags):
    # Header-only translation units intentionally leave some pin constants unused.
    return subprocess.run(
        [COMPILER, "-std=c++11", "-Wall", "-Wextra", "-Werror",
         "-x", "c++", "-fsyntax-only", *flags, "-Wno-unused-const-variable", "-"],
        input=source.replace("#pragma once", ""),
        text=True, capture_output=True, check=False, timeout=30,
    )


def resolve_build_flags(config, section, chain=()):
    # All current body profiles declare build_flags explicitly. Follow the
    # PlatformIO ${section.build_flags} references, including lab inheritance.
    # Fail closed rather than silently dropping a future unsupported option.
    if section in chain:
        raise ValueError(f"cyclic build_flags reference: {section}")
    flags = config[section]["build_flags"]
    flags = re.sub(
        r"\$\{([^{}.]+)\.build_flags\}",
        lambda match: resolve_build_flags(config, match[1], (*chain, section)),
        flags,
    )
    if "${" in flags:
        raise ValueError(f"unresolved build_flags reference in {section}")
    return flags


CONFIG = configparser.ConfigParser(interpolation=None)
assert CONFIG.read(HEADER.parent.parent / "platformio.ini", encoding="utf-8")
PROFILE_FLAGS = {
    section.removeprefix("env:"): shlex.split(resolve_build_flags(CONFIG, section))
    for section in CONFIG.sections()
    if section.startswith("env:")
}
assert PROFILE_FLAGS, "no body environments found"
STEPPER_FLAGS = PROFILE_FLAGS["esp32_full"]
DC_FLAGS = PROFILE_FLAGS["esp32_dc_full"]
ALL_PROFILES = [pytest.param(flags, id=name) for name, flags in PROFILE_FLAGS.items()]
SENSOR_PROFILES = [
    pytest.param(flags, id=name)
    for name, flags in PROFILE_FLAGS.items()
    if "-DDESK_ROBOT_STEPPER=1" in flags or "-DDESK_ROBOT_FULL_SENSORS=1" in flags
]
DC_PROFILES = [
    pytest.param(flags, id=name)
    for name, flags in PROFILE_FLAGS.items()
    if "-DDESK_ROBOT_STEPPER=1" not in flags
]


@pytest.mark.parametrize("profile,parent,extra", [
    ("esp32_full_pulse_reversed_lab", "esp32_full", "-DDESK_ROBOT_MAX30102_FIFO_IR_FIRST=1"),
    ("esp32_full_interaction_lab", "esp32_full", "-DDESK_ROBOT_ENABLE_PIR=1"),
    ("esp32_full_haptic_lab", "esp32_full", "-DDESK_ROBOT_ENABLE_HAPTIC=1"),
    ("esp32_dc_watchdog_lab", "esp32_dc_full", "-DDESK_ROBOT_ENABLE_DC_WATCHDOG=1"),
    ("esp32_dc_integrated_lab", "esp32_dc_full", "-DDESK_ROBOT_PACK_SHUNT_MOHM=5"),
])
def test_lab_profiles_retain_parent_flags(profile, parent, extra):
    flags = PROFILE_FLAGS[profile]
    inherited = PROFILE_FLAGS[parent]
    assert flags[:len(inherited)] == inherited
    assert extra in flags[len(inherited):]


@pytest.mark.parametrize("reference,diagnostic", [
    ("${env:lab.build_flags}", "cyclic"),
    ("${env.other_option}", "unresolved"),
])
def test_profile_resolver_rejects_invalid_references(reference, diagnostic):
    config = configparser.ConfigParser(interpolation=None)
    config.read_dict({"env:lab": {"build_flags": reference}})
    with pytest.raises(ValueError, match=diagnostic):
        resolve_build_flags(config, "env:lab")


@pytest.mark.parametrize("flags", ALL_PROFILES)
def test_pinmux_profiles_compile(flags):
    result = compile_header(HEADER.read_text(encoding="utf-8"), flags)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("flags", ALL_PROFILES)
@pytest.mark.parametrize("old,new,diagnostic", [
    ("kUartRx = 16", "kUartRx = 18", "WROOM GPIO allocation overlaps"),
    ("kUartTx = 17", "kUartTx = 16", "WROOM GPIO allocation overlaps"),
    ("kGripServo = 19", "kGripServo = 34", "WROOM output pin not approved"),
    ("kGripServo = 19", "kGripServo = 12", "WROOM output pin not approved"),
])
def test_common_pinmux_mutations_fail(flags, old, new, diagnostic):
    source = HEADER.read_text(encoding="utf-8")
    assert source.count(old) == 1
    result = compile_header(source.replace(old, new), flags)
    assert result.returncode != 0
    assert diagnostic in result.stderr


@pytest.mark.parametrize("flags", SENSOR_PROFILES)
@pytest.mark.parametrize("old,new", [
    ("kSensorSda = 21", "kSensorSda = 23"),
    ("kBumperInput = 35", "kBumperInput = 34"),
    ("kSensorScl = 22", "kSensorScl = 21"),
    ("kTerminalIrRightInput = 39", "kTerminalIrRightInput = 36"),
    ("kMuxReset = -1", "kMuxReset = 4"),
])
def test_pinmux_mutations_fail(flags, old, new):
    source = HEADER.read_text(encoding="utf-8")
    assert source.count(old) == 1
    result = compile_header(source.replace(old, new), flags)
    assert result.returncode != 0
    assert "static assertion failed" in result.stderr


@pytest.mark.parametrize("flags,old,new,diagnostic", [
    (STEPPER_FLAGS, "{13, 14, 25, 26}", "{13, 13, 25, 26}",
     "WROOM GPIO allocation overlaps"),
    (STEPPER_FLAGS, "{27, 32, 33, 23}", "{27, 32, 33, 26}",
     "WROOM GPIO allocation overlaps"),
    (STEPPER_FLAGS, "{27, 32, 33, 23}", "{27, 32, 33, 35}",
     "WROOM output pin not approved"),
    (STEPPER_FLAGS, "{13, 14, 25, 26}", "{13, 14, 25, 26, 16}",
     "Stepper GPIO arrays must match the eight phase owners"),
    (DC_FLAGS, "kDcHeartbeatPin = 23", "kDcHeartbeatPin = 25",
     "CPU heartbeat cannot share a DC PWM input"),
    (DC_FLAGS, "kDcHeartbeatPin = 23", "kDcHeartbeatPin = 17",
     "WROOM GPIO allocation overlaps"),
    (DC_FLAGS, "kDcHeartbeatPin = 23", "kDcHeartbeatPin = 35",
     "WROOM output pin not approved"),
])
def test_backend_specific_pinmux_mutations_fail(flags, old, new, diagnostic):
    source = HEADER.read_text(encoding="utf-8")
    assert source.count(old) == 1
    result = compile_header(source.replace(old, new), flags)
    assert result.returncode != 0
    assert "static assertion failed" in result.stderr
    assert diagnostic in result.stderr


@pytest.mark.parametrize("flags", ALL_PROFILES)
@pytest.mark.parametrize("old,new,diagnostic", [
    ("kServoChannels[] = {4, 5}", "kServoChannels[] = {4, 3}",
     "Servo outputs must own 50 Hz LEDC timer 2"),
    ("kServoFrequency = 50", "kServoFrequency = 20000",
     "Servo outputs must own 50 Hz LEDC timer 2"),
    ("kServoResolution = 16", "kServoResolution = 8",
     "Servo outputs must own 50 Hz LEDC timer 2"),
    ("kServoChannels[] = {4, 5}", "kServoChannels[] = {4, 5, 0}",
     "Servo GPIO/channel arrays must match the two servo owners"),
])
def test_servo_pwm_mutations_fail(flags, old, new, diagnostic):
    source = HEADER.read_text(encoding="utf-8")
    assert source.count(old) == 1
    result = compile_header(source.replace(old, new), flags)
    assert result.returncode != 0
    assert "static assertion failed" in result.stderr
    assert diagnostic in result.stderr


@pytest.mark.parametrize("flags", DC_PROFILES)
@pytest.mark.parametrize("old,new,diagnostic", [
    ("kMotorChannels[] = {0, 1, 2, 3}", "kMotorChannels[] = {0, 1, 2, 4}",
     "DC motor outputs must use isolated LEDC timers 0/1"),
    ("kMotorFrequency = 20000", "kMotorFrequency = 50",
     "DC motor outputs must use isolated LEDC timers 0/1"),
    ("kMotorResolution = 8", "kMotorResolution = 16",
     "DC motor outputs must use isolated LEDC timers 0/1"),
    ("kMotorChannels[] = {0, 1, 2, 3}", "kMotorChannels[] = {0, 1, 2, 3, 5}",
     "DC GPIO/channel arrays must match the four PWM owners"),
])
def test_motor_pwm_mutations_fail(flags, old, new, diagnostic):
    source = HEADER.read_text(encoding="utf-8")
    assert source.count(old) == 1
    result = compile_header(source.replace(old, new), flags)
    assert result.returncode != 0
    assert "static assertion failed" in result.stderr
    assert diagnostic in result.stderr


@pytest.mark.parametrize("relative_path,expected", [
    ("src/main.cpp", [
        "body_pins::kMotorChannels[i],body_pins::kMotorFrequency,body_pins::kMotorResolution",
        "channel,body_pins::kServoFrequency,body_pins::kServoResolution",
    ]),
    ("src/servo_center_bench.cpp", [
        "body_pins::kServoChannels[0],body_pins::kServoFrequency,body_pins::kServoResolution",
        "body_pins::kServoChannels[1],body_pins::kServoFrequency,body_pins::kServoResolution",
    ]),
    ("lib/TerminalIr/TerminalIr.cpp", []),
])
def test_pwm_setup_call_sites_preserve_timer_ownership(relative_path, expected):
    # Pin assertions alone cannot detect an extra runtime timer configuration.
    source = (HEADER.parent.parent / relative_path).read_text(encoding="utf-8")
    source = re.sub(r"//[^\n]*|/\*.*?\*/", "", source, flags=re.DOTALL)
    calls = re.findall(r"\b(ledc\w+|analogWrite\w*|tone|noTone)\s*\(", source)
    assert set(calls) <= {"ledcSetup", "ledcWrite", "ledcAttachPin", "ledcDetachPin"}
    configurations = re.findall(r"\bledcSetup\s*\(([^()]*)\)", source)
    assert calls.count("ledcSetup") == len(configurations)
    assert sorted(re.sub(r"\s+", "", args) for args in configurations) == sorted(expected)
    if relative_path == "src/main.cpp":
        assert re.search(r"for\s*\(int channel\s*:\s*body_pins::kServoChannels\)", source)
    if relative_path.startswith("lib/TerminalIr/"):
        assert not calls
        assert re.search(r"\.rmt_mode\s*=\s*RMT_MODE_RX\s*;", source)
        assert re.search(r"\brmt_rx_start\s*\(", source)
