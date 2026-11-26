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
#include "stackchan_behavior.hpp"
#include <cassert>
#include <initializer_list>
using namespace stackchan::behavior;

int main() {
    for (uint32_t start : {0U, 0xffffff00U}) {
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
