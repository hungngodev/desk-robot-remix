"""Digital activity cannot attest a residual acoustic echo or human VAD."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SENSE = Path(__file__).resolve().parents[1] / "sense"


def test_capture_does_not_inherit_previous_playback_or_future_acceptance(tmp_path):
    cxx = shutil.which(os.environ.get("CXX", "c++"))
    if not cxx:
        pytest.skip("No native C++ compiler installed")
    source = tmp_path / "echo_evidence.cc"
    source.write_text(
        """
#include <cassert>
#include <cstdint>
#include <initializer_list>
#include "sense_speaker_activity.hpp"
int main() {
    constexpr int64_t first = 1000000;
    constexpr int64_t last = first + 4000000;
    for (int64_t delta = -1; delta <= 1; ++delta) {
        for (bool fence_first : {false, true}) {
            desk_robot::SenseSpeakerActivity activity;
            const auto generation = activity.generation();
            activity.RecordAccepted(generation, 640, first - 1000);
            const auto capture = activity.BeginWindow();
            // Previous speech may still echo, but no new digital acceptance
            // has occurred. Do not report it as current capture evidence.
            assert(!activity.AdvancedSince(capture, last));
            activity.RecordAccepted(generation, 640, first - 2);
            if (fence_first) activity.FenceWindowStart(capture, first);
            activity.RecordAccepted(generation, 640, first + delta);
            if (!fence_first) activity.FenceWindowStart(capture, first);
            assert(activity.AdvancedSince(capture, last) == (delta >= 0));
        }
        desk_robot::SenseSpeakerActivity activity;
        const auto old_generation = activity.generation();
        activity.RecordAccepted(old_generation, 640, first - 1);
        activity.Reset();
        const auto capture = activity.BeginWindow();
        activity.FenceWindowStart(capture, first);
        activity.RecordAccepted(old_generation, 640, first + 1);
        assert(!activity.AdvancedSince(capture, last));
        activity.RecordAccepted(activity.generation(), 640, last + delta);
        assert(activity.AdvancedSince(capture, last) == (delta <= 0));
    }
}
""",
        encoding="utf-8",
    )
    binary = tmp_path / "echo_evidence"
    subprocess.run(
        [
            cxx, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pedantic",
            "-I", str(SENSE), str(source), "-o", str(binary),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run([str(binary)], check=True, capture_output=True, text=True)
