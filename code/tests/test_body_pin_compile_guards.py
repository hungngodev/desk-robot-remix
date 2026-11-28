"""Compile the real WROOM pin contract, including negative array mutations."""

import shutil
import subprocess
from pathlib import Path

import pytest

HEADER = Path(__file__).resolve().parents[1] / "firmware/body/include/BodyPins.h"
PROFILES = {
    "esp32dev": ("DESK_ROBOT_STEPPER=0", "DESK_ROBOT_FULL_SENSORS=0"),
    "esp32_stepper": ("DESK_ROBOT_STEPPER=1",),
    "esp32_full": ("DESK_ROBOT_STEPPER=1", "DESK_ROBOT_EXTRA_RANGERS=1"),
    "esp32_dc_full": (
        "DESK_ROBOT_STEPPER=0", "DESK_ROBOT_FULL_SENSORS=1",
        "DESK_ROBOT_ENABLE_DC_WATCHDOG=1",
    ),
    "bench_default": (),
}


@pytest.fixture(scope="module")
def compiler():
    executable = shutil.which("g++") or shutil.which("clang++")
    if executable is None:
        pytest.skip("C++ compiler required for actual static_assert verification")
    return executable


def compile_header(compiler, tmp_path, source, profile):
    (tmp_path / "BodyPins.h").write_text(source, encoding="utf-8")
    unit = tmp_path / "probe.cpp"
    unit.write_text('#include "BodyPins.h"\nint main() {}\n', encoding="utf-8")
    return subprocess.run(
        [compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror", "-pedantic-errors",
         "-fsyntax-only", *(f"-D{flag}" for flag in PROFILES[profile]), str(unit)],
        capture_output=True, text=True, timeout=30, check=False,
    )


@pytest.mark.parametrize("profile", PROFILES)
def test_valid_pin_profile_compiles(compiler, tmp_path, profile):
    result = compile_header(compiler, tmp_path, HEADER.read_text(encoding="utf-8"), profile)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(("profile", "before", "after", "diagnostic"), [
    ("esp32dev", "{kLiftServo, kGripServo}", "{kLiftServo, kGripServo, 0}", "Servo GPIO"),
    ("esp32_full", "{kLiftServo, kGripServo}", "{kLiftServo, 34}", "Servo GPIO"),
    ("esp32_dc_full", "{4, 5}", "{4, 5, 0}", "Servo GPIO"),
    ("esp32_dc_full", "{kLeftIn1, kLeftIn2, kRightIn1, kRightIn2}",
     "{kLeftIn1, kLeftIn2, kRightIn1, kRightIn2, 0}", "DC GPIO"),
    ("esp32_dc_full", "{0, 1, 2, 3}", "{0, 1, 2, 3, 4}", "DC GPIO"),
    ("esp32_full", "kRightStepperPins[2], kRightStepperPins[3]};",
     "kRightStepperPins[2], kRightStepperPins[3], 0};", "Stepper GPIO"),
    ("esp32_stepper", "{13, 14, 25, 26}", "{13, 14, 25, 26, 0}", "Stepper GPIO"),
])
def test_runtime_array_drift_fails_compilation(compiler, tmp_path, profile, before, after,
                                               diagnostic):
    source = HEADER.read_text(encoding="utf-8")
    assert source.count(before) == 1, "mutation anchor drifted"
    result = compile_header(compiler, tmp_path, source.replace(before, after), profile)
    assert result.returncode != 0, "unsafe array mutation unexpectedly compiled"
    assert diagnostic in result.stderr, result.stderr
