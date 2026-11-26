"""Compile the WROOM pin contract and reject deliberately corrupted allocations."""
import configparser
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
         "-Wno-unused-const-variable",
         "-x", "c++", "-fsyntax-only", *flags, "-"],
        input=source.replace("#pragma once", ""),
        text=True, capture_output=True, check=False,
    )


def profile_flags(profile):
    config = configparser.ConfigParser(interpolation=None)
    config.read(HEADER.parent.parent / "platformio.ini", encoding="utf-8")
    flags = config[f"env:{profile}"]["build_flags"]
    flags = flags.replace("${env.build_flags}", config["env"]["build_flags"])
    return shlex.split(flags)


LEGACY_FLAGS = profile_flags("esp32dev")
STEPPER_FLAGS = profile_flags("esp32_full")
DC_FLAGS = profile_flags("esp32_dc_full")
FULL_PROFILES = [pytest.param(STEPPER_FLAGS, id="stepper"), pytest.param(DC_FLAGS, id="dc")]
ALL_PROFILES = [pytest.param(LEGACY_FLAGS, id="legacy"), *FULL_PROFILES]


@pytest.mark.parametrize("flags", ALL_PROFILES)
def test_pinmux_profiles_compile(flags):
    result = compile_header(HEADER.read_text(encoding="utf-8"), flags)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("flags", FULL_PROFILES)
@pytest.mark.parametrize("old,new", [
    ("kUartRx = 16", "kUartRx = 18"),
    ("kSensorSda = 21", "kSensorSda = 23"),
    ("kGripServo = 19", "kGripServo = 34"),
    ("kGripServo = 19", "kGripServo = 12"),
    ("kBumperInput = 35", "kBumperInput = 34"),
    ("kUartTx = 17", "kUartTx = 16"),
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
def test_motor_pwm_mutations_fail(old, new, diagnostic):
    source = HEADER.read_text(encoding="utf-8")
    assert source.count(old) == 1
    result = compile_header(source.replace(old, new), DC_FLAGS)
    assert result.returncode != 0
    assert "static assertion failed" in result.stderr
    assert diagnostic in result.stderr
