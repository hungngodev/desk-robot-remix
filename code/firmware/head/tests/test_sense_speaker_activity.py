"""Canceled Sense I2S writes cannot qualify a fresh AEC PCM trial.

These checks establish digital generation accounting only. Physical acoustic
playback and the A2 barge-in gate still require the assembled head.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SENSE = Path(__file__).resolve().parents[1] / "sense"


def test_speaker_activity_epoch_rejects_cancelled_writes_and_old_capture(tmp_path):
    cxx = shutil.which(os.environ.get("CXX", "c++"))
    if not cxx:
        pytest.skip("No native C++ compiler installed")
    cpp = tmp_path / "speaker_activity.cc"
    cpp.write_text(
        """
#include <cassert>
#include <climits>
#include <cstdint>
#include "sense_speaker_activity.hpp"
int main() {
    desk_robot::SenseSpeakerActivity activity;
    const auto old_generation = activity.generation();
    const auto old_capture = activity.SnapshotNow();
    activity.RecordAccepted(old_generation, 160);
    assert(activity.AdvancedSince(old_capture));

    // STOP invalidates a blocking I2S writer's original generation.
    activity.Reset();
    const auto new_capture = activity.SnapshotNow();
    activity.RecordAccepted(old_generation, 320);
    assert(!activity.AdvancedSince(new_capture));
    assert(!activity.AdvancedSince(old_capture));
    activity.RecordAccepted(activity.generation(), 0);
    activity.RecordAccepted(activity.generation(), -1);
    assert(!activity.AdvancedSince(new_capture));
    activity.RecordAccepted(activity.generation(), 160);
    assert(activity.AdvancedSince(new_capture));

    // A newer STOP invalidates even the previously active capture.
    activity.Reset();
    assert(!activity.AdvancedSince(new_capture));
    const auto current = activity.SnapshotNow();
    activity.RecordAccepted(old_generation, 160);
    assert(!activity.AdvancedSince(current));
    activity.RecordAccepted(activity.generation(), INT_MAX);
    activity.RecordAccepted(activity.generation(), INT_MAX);
    activity.RecordAccepted(activity.generation(), INT_MAX);
    assert(activity.SnapshotNow().frames > UINT32_MAX);
    assert(activity.AdvancedSince(current));
}
"""
    )
    binary = tmp_path / "speaker_activity"
    subprocess.run(
        [
            cxx, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pedantic",
            "-I", str(SENSE), str(cpp), "-o", str(binary),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run([str(binary)], check=True, capture_output=True, text=True)


def test_selected_codec_requires_current_generation_activity_for_bench_capture():
    source = (SENSE / "sense_reference_codec.cc").read_text()
    header = (SENSE / "sense_reference_codec.h").read_text()
    assert "speaker_activity_.RecordAccepted(started_generation, accepted);" in source
    assert "speaker_activity_.Reset();" in source
    assert "speaker_activity_.SnapshotNow();" in source
    assert "speaker_activity_.AdvancedSince(bench_speaker_at_start_)" in source
    assert "desk_robot::SenseSpeakerActivity speaker_activity_{};" in header
    assert "desk_robot::SenseSpeakerActivity::Snapshot bench_speaker_at_start_{};" in header
    # Lifetime diagnostics still count old I2S accepts, but they cannot
    # become fresh AEC capture evidence after a STOP generation change.
    assert "speaker_frames_accepted_ += std::min(" in source
    assert "stale_publish_discards_" in source
