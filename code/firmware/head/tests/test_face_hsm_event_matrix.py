"""Exercise every HSM state/event pair and reject unregistered event IDs."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

OVERLAY = Path(__file__).resolve().parents[1] / "overlay"


def test_face_hsm_event_matrix(tmp_path):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("Native C++ compiler unavailable")
    source = tmp_path / "events.cc"
    binary = tmp_path / "events"
    source.write_text(r"""
#include "stackchan_behavior.hpp"
#include <cassert>
#include <initializer_list>
using namespace stackchan::behavior;
using S = State;
using E = EventType;

HsmBehavior in_state(S state, uint32_t start) {
    HsmBehavior pet;
    pet.pick_min_ms = pet.pick_max_ms = 10000;
    pet.sleep_after_ms = 10;
    pet.update({start});
    switch (state) {
        case S::kIdle: break;
        case S::kAttentive: pet.pushEvent(E::kPersonDetected); break;
        case S::kInteracting: pet.pushEvent(E::kTouched); break;
        case S::kTalking: pet.pushEvent(Event(E::kSpeakRequest, "hello")); break;
        case S::kSleeping: break;
        case S::kLowBattery: pet.pushEvent(E::kBatteryLow); break;
    }
    pet.update({start + (state == S::kSleeping ? 11U : 1U)});
    assert(pet.state() == state);
    return pet;
}

int main() {
    constexpr S states[] = {S::kIdle, S::kAttentive, S::kInteracting,
                            S::kTalking, S::kSleeping, S::kLowBattery};
    constexpr E events[] = {E::kTouched, E::kPersonDetected, E::kPersonLost,
                            E::kLoudSound, E::kBatteryLow, E::kCharging,
                            E::kSpeakRequest, E::kSpeechFinished};
    constexpr S I = S::kIdle, A = S::kAttentive, X = S::kInteracting;
    constexpr S T = S::kTalking, Z = S::kSleeping, L = S::kLowBattery;
    constexpr S expected[][8] = {
        {X, A, I, I, L, I, T, I},
        {X, A, I, A, L, A, T, A},
        {X, X, X, X, L, X, T, X},
        {T, T, T, T, L, T, T, I},
        {X, A, Z, I, L, Z, T, Z},
        {L, L, L, L, L, I, L, L},
    };
    assert(!isAwake(static_cast<S>(255)));
    assert(strcmp(stateName(static_cast<S>(255)), "?") == 0);
    for (uint32_t start : {0U, 0xfffffff8U}) {
        for (unsigned s = 0; s < 6; ++s) {
            const uint32_t now = start + (states[s] == Z ? 12U : 2U);
            for (unsigned e = 0; e < 8; ++e) {
                auto pet = in_state(states[s], start);
                pet.pushEvent(Event(events[e], "new"));
                const auto action = pet.update({now});
                assert(pet.state() == expected[s][e]);
                if (states[s] == L && events[e] != E::kCharging)
                    assert(action.empty() && pet.mood() == Mood::kSad);
                if (states[s] == T && events[e] == E::kTouched)
                    assert(action.empty());
                if (states[s] == T && expected[s][e] != T)
                    assert(action.set_speech && action.speech[0] == '\0');
                if (events[e] == E::kBatteryLow)
                    assert(pet.mood() == Mood::kSad);
            }
            for (unsigned id = 8; id < 256; ++id) {
                auto pet = in_state(states[s], start);
                const auto mood = pet.mood();
                pet.pushEvent(static_cast<E>(id));
                assert(pet.update({now}).empty());
                assert(pet.state() == states[s] && pet.mood() == mood);
            }
        }
        auto idle = in_state(I, start);
        idle.pushEvent(static_cast<E>(255));
        assert(idle.update({start + 11U}).mood == Mood::kSleepy);
        assert(idle.state() == Z);
        auto full = in_state(I, start);
        for (unsigned id = 8; id < 256; ++id)
            full.pushEvent(static_cast<E>(id));
        full.pushEvent(E::kBatteryLow);
        assert(full.update({start + 2U}).mood == Mood::kSad);
        assert(full.state() == L);
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
