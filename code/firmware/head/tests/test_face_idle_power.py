"""Exercise the production OLED idle policy under host sanitizers."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

OVERLAY = Path(__file__).resolve().parents[1] / "overlay"


def test_idle_power_boundaries_and_failed_write_recovery(tmp_path):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("Native C++ compiler unavailable")
    source = tmp_path / "idle.cc"
    binary = tmp_path / "idle"
    source.write_text(r"""
#include "face_idle_power.hpp"
#include <cassert>
#include <vector>
using namespace desk_robot;
int main() {
    FaceIdlePower power;
    std::vector<FacePanelMode> writes;
    bool succeed = true;
    auto apply = [&](FacePanelMode mode) {
        writes.push_back(mode);
        return succeed;
    };
    auto step = [&](uint64_t t, bool idle, bool sleeping = false) {
        power.Update(t, idle, sleeping, apply);
    };
    const uint64_t start = 0xfffffff0ULL;
    step(start, true);
    step(start + 59999, true);
    assert(writes.size() == 1 && writes.back() == FacePanelMode::kAwake);
    step(start + 60000, true);
    assert(writes.size() == 2 && writes.back() == FacePanelMode::kSoftDim);
    step(start + 60999, true, true);
    assert(writes.size() == 2);
    step(start + 61000, true, true);
    assert(writes.size() == 3 && writes.back() == FacePanelMode::kDim);
    step(start + 61999, true, true);
    assert(writes.size() == 3);
    step(start + 62000, true, true);
    assert(writes.size() == 4 && writes.back() == FacePanelMode::kOff);
    step(start + 62001, true, true);
    assert(writes.size() == 4);
    // A priority status, transcript, popup or active voice resets idle time.
    succeed = false;
    step(start + 62200, false, true);
    assert(writes.size() == 5 && writes.back() == FacePanelMode::kAwake);
    step(start + 62300, false, true);
    assert(writes.size() == 5);
    succeed = true;
    step(start + 63200, false, true);
    assert(writes.size() == 6 && writes.back() == FacePanelMode::kAwake);
    // A delayed first idle tick cannot skip either visible contrast stage.
    step(start + 63300, true, true);
    step(start + 400000, true, true);
    assert(writes.size() == 7 && writes.back() == FacePanelMode::kSoftDim);
    step(start + 400999, true, true);
    assert(writes.size() == 7);
    succeed = false;
    step(start + 401000, true, true);
    assert(writes.size() == 8 && writes.back() == FacePanelMode::kDim);
    step(start + 402000, true, true);
    assert(writes.size() == 9 && writes.back() == FacePanelMode::kDim);
    succeed = true;
    step(start + 403000, true, true);
    assert(writes.size() == 10 && writes.back() == FacePanelMode::kDim);
    step(start + 403999, true, true);
    assert(writes.size() == 10);
    // A priority wake overrides even a partially applied dim transaction.
    step(start + 404000, false);
    assert(writes.size() == 11 && writes.back() == FacePanelMode::kAwake);
    step(0, true, true);
    assert(writes.size() == 11);
}
""")
    pie_flags = [] if sys.platform == "darwin" else ["-fno-pie", "-no-pie"]
    env = dict(os.environ, UBSAN_OPTIONS="halt_on_error=1", ASAN_OPTIONS="halt_on_error=1")
    subprocess.run(
        [
            compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
            "-fsanitize=address,undefined", *pie_flags,
            "-I", str(OVERLAY), str(source), "-o", str(binary),
        ],
        check=True, timeout=60, env=env,
    )
    subprocess.run([str(binary)], check=True, timeout=30, env=env)
