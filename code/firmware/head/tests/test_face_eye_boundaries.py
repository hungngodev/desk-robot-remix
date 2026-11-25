"""Compile the integer eye easing and clock boundaries under sanitizers."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

OVERLAY = Path(__file__).resolve().parents[1] / "overlay"


def test_eye_easing_boundaries(tmp_path):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("Native C++ compiler unavailable")
    source = tmp_path / "eye_boundaries.cc"
    binary = tmp_path / "eye_boundaries"
    source.write_text(r"""
#include "face_eye_animator.hpp"
#include <cassert>
#include <limits>
using desk_robot::face_eye_detail::EaseAxis;
using desk_robot::FaceEyeAnimator;
using stackchan::behavior::Motion;
int main() {
    constexpr auto max = std::numeric_limits<uint32_t>::max();
    assert(EaseAxis(-3, 3, 0, 200) == -3);
    assert(EaseAxis(-3, 3, 0, 0) == 3);
    assert(EaseAxis(3, -3, max, 0) == -3);
    assert(EaseAxis(3, -3, max, 200) == -3);
    assert(EaseAxis(-3, 3, max / 2 + 1, max) == 0);
    assert(EaseAxis(3, -3, max / 2 + 1, max) == 0);
    assert(EaseAxis(-3, 3, max - 1, max) == 3);
    int previous = 3;
    for (uint32_t t = 0; t <= 300; ++t) {
        const int pixel = EaseAxis(3, -3, t, 300);
        assert(pixel >= -3 && pixel <= previous);
        previous = pixel;
    }
    FaceEyeAnimator eyes;
    const uint32_t start = max - 50;
    assert(eyes.Step(start, Motion::kShake, true).x == -3);
    assert(eyes.Step(start, Motion::kNone, true).x == -3);
    assert(eyes.Step(start + 450, Motion::kNone, true).x == 0);
    const auto late = eyes.Step(start + max, Motion::kNone, true);
    assert(late.x == 0 && late.y == 0 && !late.closed);
    assert(!eyes.Step(start + max, Motion::kNone, false).visible);
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
