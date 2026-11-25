"""Exercise the actual vendored HSM and OLED animator under host sanitizers."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

OVERLAY = Path(__file__).resolve().parents[1] / "overlay"


def test_face_hsm_preemption_and_timer_matrix(tmp_path):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("Native C++ compiler unavailable")
    source = tmp_path / "matrix.cc"
    binary = tmp_path / "matrix"
    source.write_text(r"""
#include "face_eye_animator.hpp"
#include <cassert>
#include <limits>
using namespace stackchan::behavior;
using desk_robot::FaceEyeAnimator;
int main() {
    for (uint32_t seed = 1; seed <= 1000; ++seed) {
        HsmBehavior pet(seed);
        FaceEyeAnimator eyes;
        const uint32_t start = 0xfffffff0U;
        auto step = [&](uint32_t t) { return pet.update({start + t}); };
        auto send = [&](EventType type) { pet.pushEvent(Event(type)); };
        auto a = step(0);
        assert(pet.state() == State::kIdle && a.mood == Mood::kNeutral);
        send(EventType::kPersonDetected);
        a = step(1);
        assert(pet.state() == State::kAttentive && a.motion == Motion::kLookFront);
        send(EventType::kPersonLost);
        assert(step(2).motion == Motion::kLookFront && pet.state() == State::kIdle);
        send(EventType::kTouched);
        a = step(3);
        assert(pet.state() == State::kInteracting && a.motion == Motion::kNod);
        assert(eyes.Step(start + 3, a.motion, true).y == 3);
        send(EventType::kBatteryLow);
        a = step(4);
        assert(pet.state() == State::kLowBattery && a.mood == Mood::kSad);
        assert(a.motion == Motion::kLookFront);
        assert(!eyes.Step(start + 4, a.motion, true).visible);
        send(EventType::kTouched);
        send(EventType::kSpeakRequest);
        assert(step(5).empty());
        send(EventType::kCharging);
        step(6);
        assert(pet.state() == State::kIdle);
        send(EventType::kTouched);
        send(EventType::kBatteryLow);
        a = step(7);
        assert(pet.state() == State::kLowBattery && a.motion == Motion::kLookFront);
        send(EventType::kCharging);
        send(EventType::kTouched);
        pet.pushEvent(Event(EventType::kSpeakRequest, nullptr));
        a = step(8);
        assert(pet.state() == State::kTalking && a.motion == Motion::kLookFront);
        assert(a.set_speech && a.speech[0] == '\0');
        send(EventType::kTouched);
        assert(step(9).empty() && pet.state() == State::kTalking);
        send(EventType::kSpeechFinished);
        assert(step(10).motion == Motion::kLookFront && pet.state() == State::kIdle);
        pet.sleep_after_ms = 100;
        assert(step(111).motion == Motion::kLookDown && pet.state() == State::kSleeping);
        send(EventType::kLoudSound);
        assert(step(112).mood == Mood::kSurprised && pet.state() == State::kIdle);
        assert(!eyes.Step(start + 112, Motion::kNod, false).visible);
        assert(!eyes.Step(start + 113, Motion::kNone, true).visible);
        // A fault or Mac mood can suppress the transition frame. At recovery
        // the HSM still owns its current mood, not the empty action's default.
        HsmBehavior offline(seed);
        offline.pick_min_ms = 6000;
        offline.pick_max_ms = 15000;
        offline.update({start});
        for (uint32_t t = 100; t <= 360000; t += 100) {
            a = offline.update({start + t});
            if (t > 300100) {
                assert(a.empty());
                assert(offline.state() == State::kSleeping);
                assert(offline.mood() == Mood::kSleepy);
            }
        }
        offline.pushEvent(Event(EventType::kLoudSound));
        a = offline.update({start + 360100});
        assert(offline.mood() == Mood::kSurprised);
        assert(offline.update({start + 360200}).empty());
        assert(offline.mood() == Mood::kSurprised);
        offline.update({start + 361600});
        assert(offline.mood() == Mood::kNeutral);
        HsmBehavior inverted(seed);
        inverted.pick_min_ms = 100;
        inverted.pick_max_ms = 1;
        inverted.update({start});
        for (uint32_t t = 1; t < 100; ++t) assert(inverted.update({start + t}).empty());
        HsmBehavior full(seed);
        full.pick_min_ms = 0;
        full.pick_max_ms = std::numeric_limits<uint32_t>::max();
        full.update({start});
        assert(full.update({start + 1}).empty());
        HsmBehavior startled(seed);
        startled.pick_min_ms = startled.pick_max_ms = 1;
        startled.update({start});
        startled.pushEvent(Event(EventType::kLoudSound));
        a = startled.update({start + 1});
        assert(a.mood == Mood::kSurprised && a.motion == Motion::kNone);
    }
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
