"""Keep the cosmetic low battery transition reliable under queue saturation."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

OVERLAY = Path(__file__).resolve().parents[1] / "overlay"


@pytest.mark.parametrize("standard", ["c++11", "c++17"])
def test_low_battery_survives_full_queue(tmp_path, standard):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("Native C++ compiler unavailable")
    source = tmp_path / "overflow.cc"
    binary = tmp_path / "overflow"
    source.write_text(r"""
#include "stackchan_behavior.hpp"
#include <cassert>
#include <initializer_list>
using namespace stackchan::behavior;
using E = EventType;
using S = State;

int main() {
    for (uint32_t start : {0U, 0xfffffff8U}) {
        for (bool talking : {false, true}) {
            HsmBehavior pet;
            pet.update({start});
            // Advance the ring head before filling it, including across wrap.
            for (unsigned i = 0; i < 5; ++i) pet.pushEvent(E::kPersonLost);
            pet.update({start + 1U});
            if (talking) {
                pet.pushEvent(Event(E::kSpeakRequest, "active"));
                assert(pet.update({start + 2U}).set_speech);
            }
            for (unsigned i = 0; i < 7; ++i) pet.pushEvent(E::kTouched);
            pet.pushEvent(E::kCharging);
            pet.pushEvent(E::kBatteryLow);
            pet.pushEvent(Event(E::kSpeakRequest, "overflow"));
            auto action = pet.update({start + 12U});
            assert(pet.state() == S::kLowBattery && pet.mood() == Mood::kSad);
            assert(action.motion == Motion::kLookFront);
            if (talking) assert(action.set_speech && action.speech[0] == '\0');
            // No routine cue may clear a low-battery expression. Unlike the
            // WROOM fault latch, this is cosmetic state only.
            for (auto cue : {E::kTouched, E::kPersonDetected, E::kPersonLost,
                             E::kLoudSound, E::kSpeakRequest, E::kSpeechFinished}) {
                pet.pushEvent(Event(cue, "ignored"));
            }
            assert(pet.update({start + 13U}).empty());
            assert(pet.state() == S::kLowBattery && pet.mood() == Mood::kSad);
            // Fresh charging retains the existing explicit recovery semantics.
            pet.pushEvent(E::kCharging);
            assert(pet.update({start + 14U}).mood == Mood::kNeutral);
            assert(pet.state() == S::kIdle);
        }
        // Ordinary overflow still drops the incoming event rather than
        // displacing an already queued low battery notification.
        HsmBehavior pet;
        pet.update({start});
        for (unsigned i = 0; i < 7; ++i) pet.pushEvent(E::kTouched);
        pet.pushEvent(E::kBatteryLow);
        pet.pushEvent(E::kCharging);
        assert(pet.update({start + 1U}).mood == Mood::kSad);
        assert(pet.state() == S::kLowBattery);
    }
}
""")
    pie_flags = [] if sys.platform == "darwin" else ["-fno-pie", "-no-pie"]
    env = dict(os.environ, UBSAN_OPTIONS="halt_on_error=1", ASAN_OPTIONS="halt_on_error=1")
    subprocess.run(
        [
            compiler, f"-std={standard}", "-Wall", "-Wextra", "-Werror", "-pedantic-errors",
            "-fsanitize=address,undefined", *pie_flags,
            "-I", str(OVERLAY), str(source), "-o", str(binary),
        ],
        check=True, timeout=60, env=env,
    )
    subprocess.run([str(binary)], check=True, timeout=30, env=env)
