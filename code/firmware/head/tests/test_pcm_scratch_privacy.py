"""Exercise the production codec Read method with a deterministic PDM fake."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("standard", ["c++11", "c++17"])
@pytest.mark.parametrize("samples", [128, 4096])
def test_pcm_scratch_is_cleared_after_read(tmp_path, standard, samples):
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
#include <functional>
#include <mutex>
#define ESP_LOGW(...) ((void)0)
int64_t esp_timer_get_time() { return 100; }
struct NoAudioCodecSimplexPdm {
    bool short_read = false;
    int read_calls = 0;
    std::function<void()> after_read;
    int Read(int16_t* dest, int frames) {
        ++read_calls;
        std::fill_n(dest, frames, 123);
        if (after_read) after_read();
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
    uint32_t short_input_reads_ = 0;
    std::atomic<uint32_t> rx_queue_overflows_{0};
    uint32_t observed_rx_queue_overflows_ = 0;
    bool reference_integrity_failed_ = false;
    bool revoke_on_reference = false;
    int reference_calls = 0;
    void FillSilenceLocked(int64_t) {}
    bool ReadReferenceLocked(int16_t* dest, int frames, int64_t) {
        ++reference_calls;
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
    constexpr int kSamples = TEST_SAMPLES;
    int16_t dest[kSamples]{};
    assert(codec.Read(dest, kSamples) == kSamples);
    for (int i = 0; i < kSamples; i += 2) {
        assert(dest[i] == 123 && dest[i + 1] == 456);
    }
    codec.AssertScratchClean();
    assert(codec.Read(dest, 32) == 32);
    codec.AssertScratchClean();
    const int refs_before_failure = codec.reference_calls;
    const uint32_t frames_before_failure = codec.microphone_frames_read_;
    codec.short_read = true;
    std::fill_n(dest, kSamples, 789);
    assert(codec.Read(dest, kSamples) == 0);
    for (auto sample : dest) assert(sample == 0);
    assert(codec.short_input_reads_ == 1 && codec.reference_integrity_failed_);
    assert(codec.reference_calls == refs_before_failure);
    assert(codec.microphone_frames_read_ == frames_before_failure);
    codec.AssertScratchClean();
    codec.short_read = false;
    // A mute/unmute cycle during a PDM read invalidates its original epoch.
    codec.after_read = [&] { codec.microphone_privacy_epoch_.fetch_add(2); };
    std::fill_n(dest, kSamples, 789);
    assert(codec.Read(dest, kSamples) == 0);
    for (auto sample : dest) assert(sample == 0);
    codec.AssertScratchClean();
    assert(codec.reference_calls == refs_before_failure);
    assert(codec.microphone_frames_read_ == frames_before_failure);
    codec.after_read = {};
    assert(codec.Read(dest, kSamples) == kSamples);
    codec.revoke_on_reference = true;
    assert(codec.Read(dest, kSamples) == 0);
    for (auto sample : dest) assert(sample == 0);
    codec.AssertScratchClean();
    const int reads_before_mute = codec.read_calls;
    std::fill_n(dest, kSamples, 789);
    assert(codec.Read(dest, kSamples) == 0);
    for (auto sample : dest) assert(sample == 0);
    assert(codec.read_calls == reads_before_mute);
    // Invalid requests must fail before touching either driver, even unmuted.
    codec.microphone_privacy_muted_.store(false);
    codec.revoke_on_reference = false;
    const int refs_before_invalid = codec.reference_calls;
    assert(codec.Read(nullptr, kSamples) == 0);
    assert(codec.Read(dest, 0) == 0);
    assert(codec.Read(dest, -2) == 0);
    assert(codec.Read(dest, 3) == 0);
    assert(codec.Read(dest, 4098) == 0);
    codec.input_sample_rate_ = 8000;
    assert(codec.Read(dest, kSamples) == 0);
    assert(codec.read_calls == reads_before_mute);
    assert(codec.reference_calls == refs_before_invalid);
    codec.AssertScratchClean();
}
''')
    executable = tmp_path / "pcm"
    subprocess.run(
        [
            compiler, f"-std={standard}", "-Wall", "-Wextra", "-Werror",
            f"-DTEST_SAMPLES={samples}", str(harness), "-o", str(executable),
        ],
        check=True,
        timeout=60,
    )
    subprocess.run([str(executable)], check=True, timeout=10)
