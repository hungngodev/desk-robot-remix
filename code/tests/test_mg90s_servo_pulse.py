"""Host pulse contracts, not physical servo travel or haptic timing evidence.

Boundary ownership:
- USB bench parser (`ServoCenterBenchGate`): rejects all numeric/raw-pulse strings.
- Full-body path (`BodyControl`): commands degrees and enforces measured endstops.
- `ServoPulse.h`: rejects invalid `[min_us, max_us]` spans (returns `0`) and clamps
  internal `pulse_us` arguments to `[min_us, max_us]` rather than acting as a
  raw-pulse command parser or proof of fitted travel safety.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BODY = ROOT / "code/firmware/body"


def _compile_and_run(source, include, executable, standard):
    compiler = shutil.which("clang++") or shutil.which("g++")
    if compiler is None:
        pytest.skip("C++ compiler unavailable")
    subprocess.run(
        [
            compiler, f"-std={standard}", "-Wall", "-Wextra", "-Wpedantic", "-Werror",
            "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
            "-fno-omit-frame-pointer", "-I", str(include), str(source), "-o", str(executable),
        ],
        check=True, capture_output=True, text=True, timeout=30,
    )
    subprocess.run([str(executable)], check=True, timeout=10)


@pytest.mark.parametrize("standard", ["c++11", "c++17"])
def test_nominal_servo_pulse_matches_center_and_command_boundaries(tmp_path, standard):
    source = tmp_path / "servo_pulse.cpp"
    source.write_text(
        '''#include "ServoPulse.h"
#include <climits>
using namespace body_pins;
static_assert(servo_duty_for_degrees(60, 1000, 2000) == 4367, "60 degrees");
static_assert(servo_duty_for_degrees(90, 1000, 2000) == 4915, "center");
static_assert(servo_duty_for_degrees(120, 1000, 2000) == 5459, "120 degrees");
static_assert(servo_duty_for_degrees(INT_MAX, INT_MIN, INT_MAX) == 0, "invalid span");
static_assert(servo_duty_for_degrees(INT_MIN, 1, 19999) == 3, "clamped low");
static_assert(servo_duty_for_degrees(INT_MAX, 1, 19999) == 65531, "clamped high");
int main() {
  for (int angle = 61; angle <= 120; ++angle) {
    if (servo_duty_for_degrees(angle, 1000, 2000) <=
        servo_duty_for_degrees(angle - 1, 1000, 2000)) return 1;
  }
  const int endpoints[] = {INT_MIN, -1, 0, 1, 2, 1000, 19999, 20000, INT_MAX};
  const int requests[] = {INT_MIN, -1, 0, 1, 90, 180, 19999, INT_MAX};
  for (int low : endpoints) {
    for (int high : endpoints) {
      const bool valid = low > 0 && low < high && high < 20000;
      for (int request : requests) {
        if (!valid) {
          if (servo_duty_for_degrees(request, low, high) != 0U ||
              servo_duty_for_microseconds(request, low, high) != 0U) return 2;
          continue;
        }
        const long long angle = request < 0 ? 0 : request > 180 ? 180 : request;
        const long long pulse = request < low ? low : request > high ? high : request;
        const auto degree_us = low + angle * (static_cast<long long>(high) - low) / 180;
        if (servo_duty_for_degrees(request, low, high) != degree_us * 65535 / 20000 ||
            servo_duty_for_microseconds(request, low, high) != pulse * 65535 / 20000) return 3;
      }
    }
  }
  return 0;
}
'''
    )
    _compile_and_run(source, BODY / "include", tmp_path / "servo_pulse", standard)


@pytest.mark.parametrize("standard", ["c++11", "c++17"])
def test_haptic_pulse_host_contract(tmp_path, standard):
    _compile_and_run(
        BODY / "tests/haptic_pulse_tests.cpp",
        BODY / "lib/AccessorySensors",
        tmp_path / "haptic_pulse",
        standard,
    )
