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
        cpp = Path(directory) / "body_boot.cc"
        exe = Path(directory) / "body_boot"
        cpp.write_text(source)
        subprocess.run(
            [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
             "-I", str(HEAD / "overlay"), str(cpp), "-o", str(exe)],
            check=True, capture_output=True, text=True,
        )
        subprocess.run([str(exe)], check=True, timeout=5)


def test_bridge_checks_matching_per_boot_status_before_face_events():
    text = (HEAD / "overlay/robot_bridge.cc").read_text()
    assert 'auto imu_boot = get(imu, "boot_id");' in text
    assert 'auto side_boot = get(side_ranges, "boot_id");' in text
    assert 'imu_boot->valuedouble != side_boot->valuedouble' in text
    assert "head_touch_edges_.AcceptBoot(" in text
    assert "body_cap_edges_.AcceptBoot(body_boot_id)" in text
    assert "head_touch_edges_.Observe(current)" in text
