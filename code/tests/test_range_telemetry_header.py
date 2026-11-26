"""Compile the telemetry header in actuator-inert body profiles."""

import shutil
import subprocess
from pathlib import Path

import pytest

HEADER = (
    Path(__file__).resolve().parents[1]
    / "firmware/body/lib/TofBus/RangeTelemetry.h"
)


@pytest.mark.parametrize(
    "defines",
    [[], ["-DDESK_ROBOT_STEPPER=0", "-DDESK_ROBOT_FULL_SENSORS=0"]],
    ids=["undefined", "explicit-zero"],
)
def test_range_telemetry_header_without_sensors(defines):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("g++ is required for the header compilation check")
    # No body or Arduino include paths: inactive telemetry must not require
    # dependencies that are unavailable in the actuator-inert profile.
    source = f'#include "{HEADER}"\n#include "{HEADER}"\n'
    result = subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", *defines,
         "-x", "c++", "-fsyntax-only", "-"],
        input=source,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
