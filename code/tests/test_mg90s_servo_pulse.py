"""The nominal MG90S duty mapping is not physical horn clearance evidence."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INCLUDE = ROOT / "code/firmware/body/include"


def test_nominal_servo_pulse_matches_center_and_command_boundaries(tmp_path):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("C++ compiler unavailable")
    source = tmp_path / "servo_pulse.cpp"
    source.write_text(
        '#include "ServoPulse.h"\n'
        'using body_pins::servo_duty_for_degrees;\n'
        'int main() {\n'
        '  static_assert(servo_duty_for_degrees(60, 1000, 2000) == 4367);\n'
        '  static_assert(servo_duty_for_degrees(90, 1000, 2000) == 4915);\n'
        '  static_assert(servo_duty_for_degrees(120, 1000, 2000) == 5459);\n'
        '  for (int angle = 61; angle <= 120; ++angle) {\n'
        '    if (servo_duty_for_degrees(angle, 1000, 2000) <=\n'
        '        servo_duty_for_degrees(angle - 1, 1000, 2000)) return 1;\n'
        '  }\n'
        '  return 0;\n'
        '}\n'
    )
    executable = tmp_path / "servo_pulse"
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-I", str(INCLUDE),
         str(source), "-o", str(executable)],
        check=True, capture_output=True, text=True, timeout=30,
    )
    subprocess.run([str(executable)], check=True, timeout=10)
