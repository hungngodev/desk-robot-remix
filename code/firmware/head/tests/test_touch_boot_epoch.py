"""Host executable checks for Sense OLED touch evidence after body reboot.

The actual WROOM motor STOP remains independent. No physical touch or
braking capability is inferred from this native counter test.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

HEAD = Path(__file__).resolve().parents[1]


def _compile_checked(compiler: str, cpp: Path, exe: Path, *,
                     toolchain_probe: bool) -> None:
    command = [
        compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
    ]
    if not toolchain_probe:
        command.extend(["-I", str(HEAD / "overlay")])
    command.extend([str(cpp), "-o", str(exe)])
    result = subprocess.run(
        command, check=False, capture_output=True, text=True, timeout=25,
    )
    if result.returncode:
        label = ("C++17 host toolchain preflight failed"
                 if toolchain_probe else
                 "Touch boot epoch product test compile failed")
        pytest.fail(
            f"{label} (exit {result.returncode})\n"
            f"compiler: {compiler}\ncommand: {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
            pytrace=False,
        )


def _check_cpp17_host(compiler: str, directory: Path) -> None:
    """Separate missing Xcode/SDK C++ headers from product source failures."""
    cpp = directory / "host_cxx17_probe.cc"
    exe = directory / "host_cxx17_probe"
    cpp.write_text(
        "#include <array>\n#include <cstdint>\n"
        "int main() { std::array<std::uint32_t, 2> a{1, 2};"
        " return a[0] != 1 || a[1] != 2; }\n",
        encoding="utf-8",
    )
    _compile_checked(compiler, cpp, exe, toolchain_probe=True)
    result = subprocess.run(
        [str(exe)], capture_output=True, text=True, timeout=5, check=False,
    )
    if result.returncode:
        pytest.fail(
            "C++17 host toolchain executable failed before product test "
            f"(exit {result.returncode}): {result.stderr}",
            pytrace=False,
        )


def test_missing_standard_array_header_identifies_toolchain_not_touch_source(
    tmp_path,
):
    """Regression: captured compiler stderr must be visible for a bad SDK."""
    fake = tmp_path / "fake-cxx"
    fake.write_text(
        "#!/bin/sh\necho 'fatal error: array file not found' >&2\nexit 1\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    with pytest.raises(pytest.fail.Exception) as error:
        _check_cpp17_host(str(fake), tmp_path)
    message = str(error.value)
    assert "C++17 host toolchain preflight failed" in message
    assert "array file not found" in message
    assert str(fake) in message


def test_body_boot_isolates_dedicated_and_cap_touch_counters():
    compiler = shutil.which("c++")
    if not compiler:
        pytest.skip("native C++ compiler unavailable")
    source = """
#include "real_touch_edges.h"
int main() {
  desk_robot::RealTouchEdges touch, cap;
  if (!touch.AcceptBoot(91) || touch.Observe(100) != 0) return 1;
  if (touch.Observe(101) != 1) return 2;
  if (!cap.AcceptBoot(91) || cap.Observe(5) != 0) return 3;
  if (cap.Observe(6) != 1) return 4;
  // Mac/Sense missed the zero row after a real WROOM reboot.
  if (!touch.AcceptBoot(92) || touch.Observe(1) != 0) return 5;
  if (!cap.AcceptBoot(92) || cap.Observe(2) != 0) return 6;
  if (touch.Observe(2) != 1 || cap.Observe(3) != 1) return 7;
  if (touch.AcceptBoot(91) || cap.AcceptBoot(91)) return 8;
  if (!touch.AcceptBoot(92) || touch.Observe(3) != 1) return 9;
  touch.Reset(); cap.Reset();  // UART failure must retain old epoch fences
  if (touch.AcceptBoot(91) || cap.AcceptBoot(91)) return 10;
  if (!touch.AcceptBoot(92) || touch.Observe(4) != 0) return 11;
  if (touch.Observe(5) != 1 || touch.Observe(100) != 0) return 12;
  return 0;
}
"""
    with tempfile.TemporaryDirectory() as directory:
        _check_cpp17_host(compiler, Path(directory))
        cpp = Path(directory) / "body_boot.cc"
        exe = Path(directory) / "body_boot"
        cpp.write_text(source, encoding="utf-8")
        _compile_checked(compiler, cpp, exe, toolchain_probe=False)
        result = subprocess.run(
            [str(exe)], check=False, capture_output=True, text=True,
            timeout=5,
        )
        if result.returncode:
            pytest.fail(
                f"Touch boot epoch product assertion failed "
                f"(exit {result.returncode}): {result.stderr}",
                pytrace=False,
            )


def test_bridge_checks_matching_per_boot_status_before_face_events():
    text = (HEAD / "overlay/robot_bridge.cc").read_text()
    assert 'auto imu_boot = get(imu, "boot_id");' in text
    assert 'auto side_boot = get(side_ranges, "boot_id");' in text
    assert 'imu_boot->valuedouble != side_boot->valuedouble' in text
    assert "head_touch_edges_.AcceptBoot(" in text
    assert "body_cap_edges_.AcceptBoot(body_boot_id)" in text
    assert "head_touch_edges_.Observe(current)" in text
