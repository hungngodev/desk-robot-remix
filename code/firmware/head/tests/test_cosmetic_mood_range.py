"""Exercise the Sense cosmetic mailbox and fault classification on a host."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

OVERLAY = Path(__file__).resolve().parents[1] / "overlay"


def test_cosmetic_mood_range_and_fault_classification(tmp_path):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("Native C++ compiler unavailable")
    source = tmp_path / "mood.cc"
    binary = tmp_path / "mood"
    source.write_text(r"""
#include "robot_protocol.h"
#include <cassert>
using namespace desk_robot;
int main() {
    constexpr CosmeticMood valid[] = {CosmeticMood::kNeutral, CosmeticMood::kHappy,
        CosmeticMood::kThinking, CosmeticMood::kSurprised};
    constexpr const char* events[] = {"mood:neutral", "mood:happy",
        "mood:thinking", "mood:surprised"};
    for (unsigned i = 0; i < 4; ++i) {
        assert(ParseCosmeticMood(events[i]) == valid[i]);
        CosmeticMoodCue cue;
        cue.offer(valid[i], 0xfffffff8U);
        assert(cue.take(8U) == valid[i]);
        assert(cue.take(8U) == CosmeticMood::kNone);
    }
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
    for (auto bad : {"", "mood:5", "mood:angry", "mood:happy ", "MOOD:HAPPY"})
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
    subprocess.run([str(binary)], check=True, timeout=30, env=env)
