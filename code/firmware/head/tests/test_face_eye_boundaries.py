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
#include "face_mood_morph.hpp"
#include <cassert>
#include <limits>
using desk_robot::face_eye_detail::EaseAxis;
using desk_robot::FaceEyeAnimator;
using desk_robot::FaceMoodMorph;
using desk_robot::BlendMoodAperture;
using stackchan::behavior::Motion;

// Seeds 1 and 13 select single and double blinks respectively. Exercise
// every millisecond, both across the scheduling wrap and across phase wrap.
void CheckBlink(uint32_t seed, uint32_t delay, bool twice, uint32_t start) {
    FaceEyeAnimator eyes;
    eyes.Seed(seed);
    const uint32_t due = start + delay;
    assert(!eyes.Step(start, Motion::kNone, true).visible);
    assert(!eyes.Step(due - 1U, Motion::kNone, true).visible);
    for (uint32_t phase = 0; phase <= 850U; ++phase) {
        const auto frame = eyes.Step(due + phase, Motion::kNone, true);
        const bool closed = (phase >= 100U && phase < 250U) ||
            (twice && phase >= 600U && phase < 750U);
        assert(frame.visible == (phase < (twice ? 850U : 350U)));
        assert(frame.closed == closed);
        assert(frame.x == 0 && frame.y == 0);
    }
}

void CheckCombined(uint32_t start) {
    FaceEyeAnimator eyes;
    FaceMoodMorph mood;
    eyes.Seed(1);
    const uint32_t due = start + 3279U;
    assert(!eyes.Step(start, Motion::kNone, true).visible);
    assert(mood.Step(start, "neutral", true) == 0);
    assert(eyes.Step(due, Motion::kLookLeft, true).x == -3);
    auto step = [&](uint32_t phase, Motion motion, const char* expression) {
        const uint32_t now = due + phase;
        auto frame = eyes.Step(now, motion, true);
        return BlendMoodAperture(frame, mood.Step(now, expression, true, frame.visible));
    };
    const auto closed = step(100, Motion::kLookRight, "surprised");
    assert(closed.visible && closed.closed && closed.x == -3 && closed.lid_height == 10);
    const auto mid = step(200, Motion::kNone, "surprised");
    assert(mid.closed && mid.x == 0 && mid.lid_height == 11);
    const auto retarget = step(249, Motion::kNone, "sleepy");
    assert(retarget.closed && retarget.lid_height == 12);
    const auto reopened = step(250, Motion::kNone, "sleepy");
    assert(reopened.visible && !reopened.closed && reopened.lid_height == 12);
    const auto steady = step(549, Motion::kNone, "sleepy");
    assert(steady.visible && !steady.closed && steady.x == 3 && steady.lid_height == 2);
    assert(!step(1200, Motion::kNone, "sleepy").visible);
}

void CheckCancellation(uint32_t start) {
    FaceEyeAnimator eyes;
    eyes.Seed(13);
    const uint32_t due = start + 3626U;
    eyes.Step(start, Motion::kNone, true);
    eyes.Step(due, Motion::kNone, true);
    assert(eyes.Step(due + 100U, Motion::kNone, true).closed);
    assert(!eyes.Step(due + 101U, Motion::kNone, false).visible);
    assert(!eyes.Step(due + 600U, Motion::kNone, true).visible);
    // Safety/rest resets the interval even if the expression gate is true.
    assert(!eyes.Step(due + 3964U, Motion::kLookRight, true, true).visible);
    assert(!eyes.Step(due + 3965U, Motion::kNone, true).visible);
    assert(!eyes.Step(due + 6964U, Motion::kNone, true).visible);
}

int main() {
    constexpr auto max = std::numeric_limits<uint32_t>::max();
    CheckBlink(1, 3279, false, max - 50U);
    CheckBlink(1, 3279, false, max - 3279U - 149U);
    CheckBlink(13, 3626, true, max - 50U);
    CheckBlink(13, 3626, true, max - 3626U - 649U);
    CheckCombined(max - 3279U - 149U);
    CheckCancellation(max - 3626U - 149U);
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
