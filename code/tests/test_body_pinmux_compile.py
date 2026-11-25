"""Compile the WROOM pin contract and reject deliberately corrupted allocations."""
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


DC_FLAGS = ["-DDESK_ROBOT_FULL_SENSORS=1", "-DDESK_ROBOT_ENABLE_DC_WATCHDOG=1"]


@pytest.mark.parametrize("flags", [[], ["-DDESK_ROBOT_STEPPER=1"], DC_FLAGS])
def test_pinmux_profiles_compile(flags):
    result = compile_header(HEADER.read_text(encoding="utf-8"), flags)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("old,new", [
    ("kUartRx = 16", "kUartRx = 18"),
    ("kSensorSda = 21", "kSensorSda = 23"),
    ("kGripServo = 19", "kGripServo = 34"),
    ("kGripServo = 19", "kGripServo = 12"),
    ("kBumperInput = 35", "kBumperInput = 34"),
])
def test_pinmux_mutations_fail(old, new):
    source = HEADER.read_text(encoding="utf-8")
    assert old in source
    result = compile_header(source.replace(old, new), DC_FLAGS)
    assert result.returncode != 0
    assert "static assertion failed" in result.stderr


@pytest.mark.parametrize("flags", [[], ["-DDESK_ROBOT_STEPPER=1"], DC_FLAGS])
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
