"""Repeated optional HSM touch events must not pin the eye nod animation."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

OVERLAY = Path(__file__).resolve().parents[1] / "overlay"


def test_repeated_touch_refreshes_mood_without_restarting_nod(tmp_path):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("Native C++ compiler unavailable")
    source = tmp_path / "pat_decay.cc"
    binary = tmp_path / "pat_decay"
    source.write_text(r'''
#include "face_eye_animator.hpp"
#include "face_mood_morph.hpp"
#include <cassert>
#include <initializer_list>
using namespace stackchan::behavior;

static void check_eye_decay(uint32_t start) {
    desk_robot::FaceEyeAnimator eyes;
    desk_robot::FaceMoodMorph mood;
    HsmBehavior pet(13);
    pet.pick_min_ms = pet.pick_max_ms = 15000;
    auto frame = [&](uint32_t t, bool pat, bool allowed = true) {
        if (pat) pet.pushEvent(Event(EventType::kTouched));
        auto action = pet.update({start + t});
        auto eye = eyes.Step(start + t, action.motion, allowed);
        auto name = pet.mood() == Mood::kSmile ? "happy" : "neutral";
        return desk_robot::BlendMoodAperture(
            eye, mood.Step(start + t, name, allowed, eye.visible));
    };
    assert(!frame(0, false).visible);
    auto first = frame(100, true);
    assert(first.y == 3 && first.lid_height == 10);
    auto middle = frame(250, true);
    assert(middle.y == 3 && middle.lid_height == 9);
    // The mood transition is over, but the original nod is still in progress.
    auto squint = frame(400, true);
    assert(squint.y == 3 && squint.lid_height == 8);
    auto settle = frame(650, true);
    assert(settle.y == -2 && settle.lid_height == 8);
    assert(!frame(1200, true).visible);  // stock happy glyph resumes
    assert(!frame(1300, true).visible);
    frame(6300, false);
    assert(pet.state() == State::kInteracting && pet.mood() == Mood::kSmile);
    auto decay = frame(6301, false);
    assert(decay.visible && decay.lid_height == 8);
    decay = frame(6451, false);
    assert(decay.visible && decay.lid_height == 9);
    // A display priority gate cancels both overlays immediately.
    assert(!frame(6452, false, false).visible);
    assert(!frame(6453, false).visible);
}

int main() {
    for (uint32_t start : {0U, 0xffffff00U}) {
        check_eye_decay(start);
        HsmBehavior pet(13);
        pet.pick_min_ms = pet.pick_max_ms = 15000;
        auto step = [&](uint32_t t) { return pet.update({start + t}); };
        auto pat = [&]() { pet.pushEvent(Event(EventType::kTouched)); };
        step(0);
        pat();
        pat();
        auto action = step(100);
        assert(action.set_mood && action.mood == Mood::kSmile);
        assert(action.motion == Motion::kNod);
        for (uint32_t t = 200; t <= 3000; t += 100) {
            pat();
            assert(step(t).empty());
            assert(pet.state() == State::kInteracting && pet.mood() == Mood::kSmile);
        }
        assert(step(8000).empty());
        action = step(8001);
        assert(action.set_mood && action.mood == Mood::kNeutral);
        assert(action.motion == Motion::kLookFront && pet.state() == State::kIdle);
        pat();
        assert(step(8100).motion == Motion::kNod);
        pet.pushEvent(Event(EventType::kSpeakRequest, "hello"));
        pat();
        action = step(8200);
        assert(action.set_speech && action.motion == Motion::kLookFront);
        assert(pet.state() == State::kTalking && pet.mood() == Mood::kNeutral);
        pet.pushEvent(Event(EventType::kBatteryLow));
        pat();
        action = step(8300);
        assert(action.motion == Motion::kLookFront && action.mood == Mood::kSad);
        assert(pet.state() == State::kLowBattery);
    }
}
''')
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
