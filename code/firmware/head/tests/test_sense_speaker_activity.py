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
    const auto old_capture = activity.BeginWindow();
    activity.RecordAccepted(old_generation, 160, 10000);
    assert(activity.AdvancedSince(old_capture, 10000));

    // STOP invalidates a blocking I2S writer's original generation.
    activity.Reset();
    const auto new_capture = activity.BeginWindow();
    activity.RecordAccepted(old_generation, 320, 15000);
    assert(!activity.AdvancedSince(new_capture, 20000));
    assert(!activity.AdvancedSince(old_capture, 10000));
    activity.RecordAccepted(activity.generation(), 0, 15001);
    activity.RecordAccepted(activity.generation(), -1, 15002);
    assert(!activity.AdvancedSince(new_capture, 20000));
    activity.RecordAccepted(activity.generation(), 160, 20000);
    assert(activity.AdvancedSince(new_capture, 20000));

    // A newer STOP invalidates even the previously active capture.
    activity.Reset();
    assert(!activity.AdvancedSince(new_capture, 20000));
    const auto current = activity.BeginWindow();
    activity.RecordAccepted(old_generation, 160, 10000);
    assert(!activity.AdvancedSince(current, 30000));
    activity.RecordAccepted(activity.generation(), INT_MAX, 30000);
    activity.RecordAccepted(activity.generation(), INT_MAX, 30000);
    activity.RecordAccepted(activity.generation(), INT_MAX, 30000);
    assert(activity.SnapshotNow().frames > UINT32_MAX);
    assert(activity.AdvancedSince(current, 30000));

    // An accepted I2S callback AFTER the final mic sample cannot be
    // misreported as speaker activity inside the recorded PCM window.
    activity.Reset();
    const auto before_last_mic_frame = activity.BeginWindow();
    activity.RecordAccepted(activity.generation(), 320, 60001);
    assert(!activity.AdvancedSince(before_last_mic_frame, 60000));
    activity.RecordAccepted(activity.generation(), 320, 60002);
    assert(!activity.AdvancedSince(before_last_mic_frame, 60000));
    assert(activity.AdvancedSince(before_last_mic_frame, 60001));

    // Later digital acceptance must not mask earlier valid activity.
    activity.Reset();
    const auto valid_window = activity.BeginWindow();
    activity.RecordAccepted(activity.generation(), 160, 70000);
    activity.RecordAccepted(activity.generation(), 160, 71000);
    assert(activity.AdvancedSince(valid_window, 70500));
    assert(!activity.AdvancedSince(valid_window, 69999));
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
    assert "speaker_activity_.RecordAccepted(" in source
    assert "started_generation, accepted, accepted_at_us);" in source
    assert "const int64_t accepted_at_us = esp_timer_get_time();" in source
    assert "speaker_activity_.Reset();" in source
    assert "speaker_activity_.BeginWindow();" in source
    assert "speaker_activity_.AdvancedSince(bench_speaker_at_start_, capture_end_us)" in source
    assert "desk_robot::SenseSpeakerActivity speaker_activity_{};" in header
    assert "desk_robot::SenseSpeakerActivity::Snapshot bench_speaker_at_start_{};" in header
    # Lifetime diagnostics still count old I2S accepts, but they cannot
    # become fresh AEC capture evidence after a STOP generation change.
    assert "speaker_frames_accepted_ += std::min(" in source
    assert "stale_publish_discards_" in source
