"""Compile the WROOM pin contract and reject deliberately corrupted allocations."""
import shutil
import subprocess
from pathlib import Path

import pytest

HEADER = Path(__file__).resolve().parents[1] / "firmware/body/include/BodyPins.h"
COMPILER = shutil.which("g++")
pytestmark = pytest.mark.skipif(COMPILER is None, reason="g++ is unavailable")


def compile_header(source, flags):
    return subprocess.run(
        [COMPILER, "-std=c++11", "-Wall", "-Wextra", "-Werror",
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
