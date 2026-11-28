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
#include "face_eye_animator.hpp"
#include "face_mood_morph.hpp"
#include "face_presence.hpp"
#include "robot_protocol.h"
#include <algorithm>
#include <array>
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

// The HSM has a low-battery event, not a WROOM motor-fault event.
static void CheckQueuedPreemption(S state, uint32_t start) {
    std::array<E, 3> queued{E::kTouched, E::kBatteryLow, E::kSpeakRequest};
    do {
        auto pet = in_state(state, start);
        for (auto event : queued) pet.pushEvent(Event(event, "receipt speech"));
        const auto action = pet.update({start + 12U});
        assert(pet.state() == S::kLowBattery && pet.mood() == Mood::kSad);
        assert(!action.set_speech || action.speech[0] == '\0');
        if (state != S::kLowBattery) assert(action.motion == Motion::kLookFront);
        if (state == S::kTalking) assert(action.set_speech);
        assert(pet.update({start + 13U}).empty());
    } while (std::next_permutation(queued.begin(), queued.end()));
}

// Exercise the production primitives at the FaceTask boundary. A model mood
// cue is cosmetic, not evidence that an MCP tool completed or audio played.
static void CheckFaultGate(uint32_t start) {
    using namespace desk_robot;
    for (bool dock : {false, true}) {
        for (bool privacy : {false, true}) {
            for (bool link_lost : {false, true}) {
                auto pet = in_state(S::kIdle, start);
                FaceEyeAnimator eyes;
                FaceMoodMorph morph;
                CosmeticMoodCue cue;
                pet.pushEvent(E::kTouched);
                auto action = pet.update({start + 2U});
                assert(eyes.Step(start + 2U, action.motion, true).visible);
                morph.Step(start + 2U, "happy", true);
                cue.offer(CosmeticMood::kThinking, start + 3U);
                pet.pushEvent(Event(E::kSpeakRequest, "receipt speech"));
                pet.pushEvent(E::kTouched);
                action = pet.update({start + 12U});
                assert(pet.state() == S::kTalking && pet.mood() == Mood::kNeutral);
                assert(action.motion == Motion::kLookFront);
                const auto status = SelectFaceStatus(true, dock, privacy, link_lost);
                assert(status == (dock ? FaceStatus::kDockLock : FaceStatus::kBodyFault));
                const bool blocked = FaceStatusBlocksExpression(status);
                assert(blocked);
                // Model the consumer drain while the renderer is suppressed.
                assert(cue.take(start + 12U) == CosmeticMood::kThinking);
                assert(!eyes.Step(start + 12U, action.motion, !blocked, blocked).visible);
                assert(!eyes.Step(start + 12U, Motion::kNod, !blocked, blocked).visible);
                assert(morph.Step(start + 12U, "thinking", !blocked) == 0);
                // Recovery precedes the cue TTL: it must have been consumed,
                // rather than merely expiring before it can be replayed.
                assert(cue.take(start + 13U) == CosmeticMood::kNone);
                pet.pushEvent(E::kSpeechFinished);
                action = pet.update({start + 14U});
                assert(pet.state() == S::kIdle && action.set_speech);
                assert(action.speech[0] == '\0');
                assert(!eyes.Step(start + 14U, action.motion, true).visible);
                assert(morph.Step(start + 14U, "neutral", true) == 0);
            }
        }
    }
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
        CheckFaultGate(start);
        for (unsigned s = 0; s < 6; ++s) {
            CheckQueuedPreemption(states[s], start);
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
