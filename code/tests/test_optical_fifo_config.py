"""Reject malformed channel selections and exercise the configured decoder."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("flag, expected", [(None, 0), ("0", 0), ("1", 1),
                                             ("2", None), ("-1", None),
                                             ("typo", None)])
def test_optical_fifo_config(tmp_path, flag, expected):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if compiler is None:
        pytest.skip("C++ compiler unavailable")
    header = Path(__file__).resolve().parents[1] / "firmware/body/lib/PulsePad"
    source = tmp_path / "probe.cpp"
    source.write_text(
        '#include "OpticalRaw.h"\n'
        'int main() {\n'
        '  const std::uint8_t fifo[] = {0, 0, 7, 0, 0, 19};\n'
        '  auto c = desk_robot::decode_optical_channels(fifo, desk_robot::kOpticalFifoIrFirst);\n'
        f'  return c.red == {19 if expected else 7} && '
        f'c.ir == {7 if expected else 19} ? 0 : 1;\n'
        '}\n'
    )
    exe = tmp_path / "probe"
    cmd = [compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror", "-I", str(header)]
    if flag is not None:
        cmd.append(f"-DDESK_ROBOT_MAX30102_FIFO_IR_FIRST={flag}")
    result = subprocess.run(cmd + [str(source), "-o", str(exe)], capture_output=True,
                            text=True, timeout=30)
    if expected is None:
        assert result.returncode != 0
    else:
        assert result.returncode == 0, result.stderr
        subprocess.run([str(exe)], check=True, timeout=10)
