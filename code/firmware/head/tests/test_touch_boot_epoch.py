"""Host executable checks for Sense OLED touch evidence after body reboot.

The actual WROOM motor STOP remains independent. No physical touch or
braking capability is inferred from this native counter test.
"""
from __future__ import annotations

import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

HEAD = Path(__file__).resolve().parents[1]


def _darwin_cxx_flags() -> list[str]:
    flags: list[str] = []
    if platform.system() == "Darwin":
        for sdk in (
            Path("/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk"),
            Path("/Library/Developer/CommandLineTools/SDKs/MacOSX15.4.sdk"),
        ):
            if sdk.exists():
                flags.extend(["-isysroot", str(sdk), "-stdlib=libc++"])
                inc = sdk / "usr/include/c++/v1"
                if inc.exists():
                    flags.extend(["-I", str(inc)])
                break
    return flags


def _compile_checked(compiler: str, cpp: Path, exe: Path, *,
                     toolchain_probe: bool) -> None:
    command = [
        compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
    ]
    command.extend(_darwin_cxx_flags())
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
  // A zero epoch is never emitted by WROOM. Reject it before *any* edge
  // baseline, and refuse to reuse a baseline after an invalid report.
  desk_robot::RealTouchEdges zero;
  if (zero.AcceptBoot(0)) return 13;
  if (!zero.AcceptBoot(91) || zero.Observe(10) != 0) return 14;
  if (zero.Observe(11) != 1) return 15;
  if (zero.AcceptBoot(0)) return 16;
  if (!zero.AcceptBoot(91) || zero.Observe(99) != 0) return 17;
  if (zero.Observe(100) != 1) return 18;
  // An invalid zero must not become a legitimate post-reboot epoch.
  if (!zero.AcceptBoot(92) || zero.Observe(1) != 0) return 19;
  if (zero.AcceptBoot(0) || zero.AcceptBoot(91)) return 20;
  if (!zero.AcceptBoot(92) || zero.Observe(2) != 0) return 21;
  if (zero.Observe(3) != 1) return 22;
  // Same-boot stale samples must not lower the counter watermark or turn
  // the previously seen count into a fresh touch, even across UART failures.
  desk_robot::RealTouchEdges replay;
  if (!replay.AcceptBoot(91) || replay.Observe(100) != 0) return 23;
  if (replay.Observe(98) != 0 || replay.Observe(100) != 0) return 24;
  if (replay.Observe(101) != 1) return 25;
  replay.Reset();
  if (replay.Observe(99) != 0 || replay.Observe(101) != 0) return 26;
  if (replay.Observe(102) != 1) return 27;
  if (replay.Observe(102u + 0x80000000u) != 0 ||
      replay.Observe(103) != 1) return 28;
  if (!replay.AcceptBoot(92) || replay.Observe(0xfffffffeu) != 0) return 29;
  if (replay.Observe(0xffffffffu) != 1 || replay.Observe(0) != 1) return 30;
  if (replay.Observe(0xffffffffu) != 0 || replay.Observe(0) != 0 ||
      replay.Observe(1) != 1) return 31;
  if (replay.AcceptBoot(91) || !replay.AcceptBoot(92) ||
      replay.Observe(2) != 1) return 32;
  desk_robot::RealTouchEdges no_boot;
  if (no_boot.Observe(10) != 0 || no_boot.Observe(11) != 0) return 33;
  // Rejected epochs must not emit or poison the active watermark, even
  // if a future caller accidentally forwards their counters.
  desk_robot::RealTouchEdges rejected;
  if (!rejected.AcceptBoot(91) || rejected.Observe(100) != 0 ||
      !rejected.AcceptBoot(92) || rejected.Observe(10) != 0) return 34;
  if (rejected.AcceptBoot(91) || rejected.Observe(11) != 0) return 35;
  if (!rejected.AcceptBoot(92) || rejected.Observe(11) != 1) return 36;
  if (rejected.AcceptBoot(0) || rejected.Observe(500) != 0 ||
      rejected.Observe(501) != 0) return 37;
  if (!rejected.AcceptBoot(92) || rejected.Observe(12) != 0 ||
      rejected.Observe(13) != 1) return 38;
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


def test_bridge_rejects_zero_wroom_boot_before_a_healthy_face():
    """A zero epoch must not validate or publish a WROOM status report."""
    bridge = (HEAD / "overlay/robot_bridge.cc").read_text()
    body = (HEAD.parent / "body/src/main.cpp").read_text()
    assert "control.set_boot_epoch(esp_random() | 1U);" in body
    assert "!integer(imu_boot, 1, 4294967295.0)" in bridge
    assert "!integer(side_boot, 1, 4294967295.0)" in bridge
    assert "boot->valuedouble < 1 || boot->valuedouble > 4294967295.0" in bridge


def test_wroom_touch_poll_rejects_inter_sample_bounce_and_stops_before_bus(tmp_path):
    """Execute the actual GPIO polling function with fake hardware boundaries."""
    compiler = shutil.which("c++")
    if not compiler:
        pytest.skip("native C++ compiler unavailable")
    body = (HEAD.parent / "body/src/main.cpp").read_text()
    start = body.index("void poll_touch(std::uint32_t now_ms) {")
    end = body.index("\n}\n", start) + 3
    loop = body.split("void loop() {", 1)[1]
    assert loop.index("poll_touch(millis());") < loop.index("tof.poll(")
    cpp = tmp_path / "raw_touch.cc"
    exe = tmp_path / "raw_touch"
    cpp.write_text(
        """
#include <cassert>
#include <cstdint>
namespace body_pins { constexpr int kTouchOutput=34; }
constexpr int HIGH=1;
bool raw=false;
int digitalRead(int) { return raw; }
struct Control {
  struct State { bool armed=true; bool touch_raw_active=false; } s;
  unsigned edges=0;
  State const& state() const { return s; }
  void sample_touch_input(bool a) { s.touch_raw_active=a; if(a) s.armed=false; }
  void set_touch(bool a, std::uint32_t) { if(a) ++edges; }
} control;
unsigned output_calls=0;
void apply_outputs() { assert(!control.state().armed); ++output_calls; }
bool touch_stable=false, touch_candidate=false;
std::uint8_t touch_candidate_samples=0;
std::uint32_t touch_last_sample_ms=0;
""" + body[start:end] + """
void sample(std::uint32_t t,bool a){raw=a;poll_touch(t);}
int main(){
  // Three 1ms pulses coincident with nominal 25ms sample instants.
  for(std::uint32_t t=0;t<=100;++t) sample(t,t==25||t==50||t==75);
  assert(control.edges==0);
  assert(!control.state().armed);
  assert(output_calls==1);
  for(std::uint32_t t=101;t<=60101;++t) sample(t,true);
  assert(control.edges==1 && touch_stable && output_calls==1);
  for(std::uint32_t t=60102;t<=60160;++t) sample(t,false);
  assert(!touch_stable && control.edges==1);
  touch_last_sample_ms=0xffffffe0u;
  sample(0xfffffff0u,true);
  sample(8,true); assert(!touch_stable);
  sample(9,true); assert(!touch_stable);
  sample(33,true); assert(!touch_stable);
  sample(34,true); assert(touch_stable && control.edges==2);
}
""",
        encoding="utf-8",
    )
    _compile_checked(compiler, cpp, exe, toolchain_probe=False)
    result = subprocess.run(
        [str(exe)], check=False, capture_output=True, text=True, timeout=5,
    )
    assert result.returncode == 0, result.stderr
