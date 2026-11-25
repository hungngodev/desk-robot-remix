"""Exercise the production codec Read method with a deterministic PDM fake."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


def test_pcm_scratch_is_cleared_after_read(tmp_path):
    compiler = shutil.which(os.environ.get("CXX", "c++"))
    if compiler is None:
        pytest.skip("C++ compiler unavailable")
    source = (Path(__file__).resolve().parents[1] / "sense/sense_reference_codec.cc").read_text()
    read = "int SenseReferenceCodec::Read(" + source.split(
        "int SenseReferenceCodec::Read(", 1
    )[1].split("int SenseReferenceCodec::Write(", 1)[0]
    harness = tmp_path / "pcm.cpp"
    harness.write_text(r'''
#include <algorithm>
#include <array>
#include <atomic>
#include <cassert>
#include <cstdint>
#include <mutex>
#define ESP_LOGW(...) ((void)0)
int64_t esp_timer_get_time() { return 100; }
struct NoAudioCodecSimplexPdm {
    bool short_read = false;
    int Read(int16_t* dest, int frames) {
        std::fill_n(dest, frames, 123);
        return short_read ? frames - 1 : frames;
    }
};
struct SenseReferenceCodec : NoAudioCodecSimplexPdm {
    static constexpr int kMicRate = 16000, kMaxReadFrames = 2048;
    int input_sample_rate_ = kMicRate;
    std::atomic<bool> microphone_privacy_muted_{false};
    std::atomic<uint32_t> microphone_privacy_epoch_{0};
    std::mutex input_read_mutex_, reference_mutex_;
    std::array<int16_t, kMaxReadFrames> microphone_frame_{}, reference_frame_{};
    uint32_t microphone_frames_read_ = 0, reference_overwrite_reads_ = 0;
    uint32_t consecutive_missing_reference_reads_ = 0;
    bool revoke_on_reference = false;
    void FillSilenceLocked(int64_t) {}
    bool ReadReferenceLocked(int16_t* dest, int frames, int64_t) {
        std::fill_n(dest, frames, 456);
        if (revoke_on_reference) {
            microphone_privacy_muted_.store(true);
            microphone_privacy_epoch_.fetch_add(1);
        }
        return true;
    }
    int Read(int16_t*, int);
    void AssertScratchClean() const {
        for (auto sample : microphone_frame_) assert(sample == 0);
        for (auto sample : reference_frame_) assert(sample == 0);
    }
};
''' + read + r'''
int main() {
    SenseReferenceCodec codec;
    int16_t dest[128]{};
    assert(codec.Read(dest, 128) == 128);
    for (int i = 0; i < 128; i += 2) {
        assert(dest[i] == 123 && dest[i + 1] == 456);
    }
    codec.AssertScratchClean();
    assert(codec.Read(dest, 32) == 32);
    codec.AssertScratchClean();
    codec.short_read = true;
    assert(codec.Read(dest, 128) == 0);
    codec.AssertScratchClean();
    codec.short_read = false;
    codec.revoke_on_reference = true;
    assert(codec.Read(dest, 128) == 0);
    for (auto sample : dest) assert(sample == 0);
    codec.AssertScratchClean();
    assert(codec.Read(dest, 128) == 0);
    codec.AssertScratchClean();
}
''')
    executable = tmp_path / "pcm"
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", str(harness), "-o", str(executable)],
        check=True,
        timeout=60,
    )
    subprocess.run([str(executable)], check=True, timeout=10)
