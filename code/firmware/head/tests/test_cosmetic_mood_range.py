"""Exercise the Sense cosmetic mailbox and fault classification on a host."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from desk_robot.expression_policy import _MODEL_MOODS, model_mood_event

OVERLAY = Path(__file__).resolve().parents[1] / "overlay"


def test_cosmetic_mood_range_and_fault_classification(tmp_path):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("Native C++ compiler unavailable")
    moods = ("neutral", "happy", "thinking", "surprised")
    assert _MODEL_MOODS == frozenset(moods)
    events = [model_mood_event(mood) for mood in moods]
    assert events == [f"mood:{mood}" for mood in moods]
    for mood in ("sleepy", "sad", "angry", "none", "happy:14", 14, 0.5):
        assert model_mood_event(mood) is None
    source = tmp_path / "mood.cc"
    binary = tmp_path / "mood"
    source.write_text(r"""
#include "face_mood_morph.hpp"
#include "robot_protocol.h"
#include <cassert>
using namespace desk_robot;
static void CheckTransitions(char** events) {
    constexpr uint8_t heights[] = {10, 8, 9, 14};
    for (uint32_t start : {0U, 0xfffffff0U}) {
        for (unsigned i = 0; i < 4; ++i) {
            for (unsigned j = 0; j < 4; ++j) {
                const auto from = std::string_view(events[i]).substr(5);
                const auto to = std::string_view(events[j]).substr(5);
                FaceMoodMorph face;
                assert(face.Step(start, from, true, true) == heights[i]);
                assert(face.Step(start + 1, to, true, true) == heights[i]);
                auto previous = heights[i];
                for (uint32_t age = 1; age <= FaceMoodMorph::kDurationMs; ++age) {
                    const auto height = face.Step(start + 1 + age, to, true, true);
                    if (heights[i] <= heights[j]) {
                        assert(height >= previous && height <= heights[j]);
                    } else {
                        assert(height <= previous && height >= heights[j]);
                    }
                    previous = height;
                }
                assert(previous == heights[j]);
                assert(face.Step(start + 301, to, true) == 0);
                assert(face.Step(start + 302, to, false, true) == 0);
            }
        }
    }
}

int main(int argc, char** argv) {
    assert(argc == 5);
    auto events = argv + 1;
    constexpr CosmeticMood valid[] = {CosmeticMood::kNeutral, CosmeticMood::kHappy,
        CosmeticMood::kThinking, CosmeticMood::kSurprised};
    for (unsigned i = 0; i < 4; ++i) {
        assert(ParseCosmeticMood(events[i]) == valid[i]);
        CosmeticMoodCue cue;
        cue.offer(valid[i], 0xfffffff8U);
        assert(cue.take(8U) == valid[i]);
        assert(cue.take(8U) == CosmeticMood::kNone);
    }
    CheckTransitions(events);
    for (unsigned raw = 0; raw <= 255; ++raw) {
        if (raw >= 1 && raw <= 4) continue;
        const auto invalid = static_cast<CosmeticMood>(raw);
        CosmeticMoodCue cue;
        cue.offer(invalid, 1024U);
        assert(cue.take(1280U) == CosmeticMood::kNone);
        cue.offer(CosmeticMood::kThinking, 1024U);
        cue.offer(invalid, 1032U);
        assert(cue.take(1040U) == CosmeticMood::kThinking);
    }
    for (auto bad : {"", "mood:5", "mood:angry", "mood:sad", "mood:sleepy",
                     "mood:happy:14", "mood:happy ", "MOOD:HAPPY"})
        assert(ParseCosmeticMood(bad) == CosmeticMood::kNone);
    for (auto fault : {"OFFLINE_NO_MAC", "offline_no_mac", "CLIFF", "cliff",
                       "FAULT", "unknown", ""})
        assert(BodySafetyUnhealthy(true, true, fault));
    assert(!BodySafetyUnhealthy(true, true, "none"));
    assert(BodySafetyUnhealthy(false, true, "none"));
    assert(BodySafetyUnhealthy(true, false, "none"));
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
    subprocess.run([str(binary), *events], check=True, timeout=30, env=env)
