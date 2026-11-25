"""Source regression for a PDM reader queued across a BOOT privacy change.

Physical microphone and network silence still require the assembled head trial.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

CODEC = Path(__file__).resolve().parents[1] / "sense" / "sense_reference_codec.cc"


def _read():
    return CODEC.read_text().split("int SenseReferenceCodec::Read(", 1)[1].split(
        "int SenseReferenceCodec::Write(", 1
    )[0]


def test_queued_pdm_read_rechecks_consent_after_acquiring_reader_mutex():
    read = _read()
    after_lock = read.split("input_lock(input_read_mutex_);", 1)[1]
    before_pdm = after_lock.split("NoAudioCodecSimplexPdm::Read(", 1)[0]
    assert "if (microphone_privacy_muted_.load(std::memory_order_acquire) ||" in before_pdm
    assert "privacy_epoch != microphone_privacy_epoch_.load(" in before_pdm
    assert "return 0;" in before_pdm


def test_partial_pdm_read_erases_private_scratch_before_return():
    read = _read()
    failed = read.split("if (mic_read != frames) {", 1)[1].split("\n    }\n", 1)[0]
    assert failed.index("std::fill_n(microphone_frame_.begin(), frames, 0);") < failed.index(
        "return 0;"
    )


def test_pdm_consent_revocation_while_reader_waits_or_mixes(tmp_path):
    """Compile the actual Read body against a deterministic blocking PDM fake."""
    compiler = shutil.which("c++")
    if not compiler:
        pytest.skip("native C++ compiler unavailable")
    preamble = r'''
#include <algorithm>
#include <array>
#include <atomic>
#include <cassert>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <mutex>
#include <thread>
#define ESP_LOGW(...) ((void)0)
int64_t esp_timer_get_time() { return 1; }

struct EpochProbe {
    std::atomic<uint32_t> value{0};
    std::atomic<unsigned> loads{0};
    uint32_t load(std::memory_order order) {
        const auto epoch = value.load(order);
        loads.fetch_add(1);
        return epoch;
    }
};

struct NoAudioCodecSimplexPdm {
    std::mutex pdm_mutex;
    std::condition_variable pdm_cv;
    bool entered = false;
    bool release = false;
    bool short_read = false;
    unsigned hardware_reads = 0;
    int Read(int16_t* dest, int frames) {
        std::unique_lock<std::mutex> lock(pdm_mutex);
        ++hardware_reads;
        if (hardware_reads == 1) {
            entered = true;
            pdm_cv.notify_all();
            pdm_cv.wait(lock, [&] { return release; });
        }
        std::fill_n(dest, frames, 123);
        return short_read ? frames - 1 : frames;
    }
};

struct SenseReferenceCodec : NoAudioCodecSimplexPdm {
    static constexpr int kMicRate = 16000;
    static constexpr int kMaxReadFrames = 2048;
    int input_sample_rate_ = kMicRate;
    EpochProbe microphone_privacy_epoch_;
    std::atomic<bool> microphone_privacy_muted_{false};
    std::mutex input_read_mutex_, reference_mutex_;
    std::array<int16_t, kMaxReadFrames> microphone_frame_{}, reference_frame_{};
    uint32_t microphone_frames_read_ = 0;
    uint32_t short_input_reads_ = 0;
    bool reference_integrity_failed_ = false;
    uint32_t reference_overwrite_reads_ = 0;
    uint32_t consecutive_missing_reference_reads_ = 0;
    bool revoke_while_mixing = false;
    void SetMuted(bool muted) {
        if (microphone_privacy_muted_.exchange(muted) != muted)
            microphone_privacy_epoch_.value.fetch_add(1);
    }
    void FillSilenceLocked(int64_t) {}
    bool ReadReferenceLocked(int16_t* dest, int frames, int64_t) {
        std::fill_n(dest, frames, 456);
        if (revoke_while_mixing) SetMuted(true);
        return true;
    }
    int Read(int16_t* dest, int samples);
};
'''
    exercise = r'''
int main() {
    SenseReferenceCodec codec;
    std::array<int16_t, 16> first{}, queued{}, fresh{};
    int first_result = -1, queued_result = -1;
    std::thread active([&] { first_result = codec.Read(first.data(), first.size()); });
    {
        std::unique_lock<std::mutex> lock(codec.pdm_mutex);
        assert(codec.pdm_cv.wait_for(lock, std::chrono::seconds(2),
                                    [&] { return codec.entered; }));
    }
    const unsigned prior_loads = codec.microphone_privacy_epoch_.loads.load();
    std::thread waiting([&] { queued_result = codec.Read(queued.data(), queued.size()); });
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(2);
    while (codec.microphone_privacy_epoch_.loads.load() == prior_loads) {
        assert(std::chrono::steady_clock::now() < deadline);
        std::this_thread::yield();
    }
    codec.SetMuted(true);
    codec.SetMuted(false);  // even a rapid deliberate unmute cannot reuse old capture
    {
        std::lock_guard<std::mutex> lock(codec.pdm_mutex);
        codec.release = true;
        codec.pdm_cv.notify_all();
    }
    active.join(); waiting.join();
    assert(first_result == 0 && queued_result == 0);
    assert(codec.hardware_reads == 1);
    assert(codec.microphone_frame_[0] == 0);
    assert(codec.Read(fresh.data(), fresh.size()) == static_cast<int>(fresh.size()));
    assert(codec.hardware_reads == 2 && fresh[0] == 123 && fresh[1] == 456);
    assert(codec.short_input_reads_ == 0 && !codec.reference_integrity_failed_);
    const auto frames_before = codec.microphone_frames_read_;
    codec.short_read = true;
    assert(codec.Read(fresh.data(), fresh.size()) == 0);
    assert(codec.microphone_frame_[0] == 0);
    assert(codec.short_input_reads_ == 1 && codec.reference_integrity_failed_);
    assert(codec.microphone_frames_read_ == frames_before);
    codec.short_input_reads_ = UINT32_MAX - 1;
    assert(codec.Read(fresh.data(), fresh.size()) == 0);
    assert(codec.Read(fresh.data(), fresh.size()) == 0);
    assert(codec.short_input_reads_ == UINT32_MAX);
    codec.short_read = false;
    assert(codec.Read(fresh.data(), fresh.size()) == static_cast<int>(fresh.size()));
    assert(codec.reference_integrity_failed_);
    codec.revoke_while_mixing = true;
    assert(codec.Read(fresh.data(), fresh.size()) == 0);
    assert(std::all_of(fresh.begin(), fresh.end(), [](int16_t s) { return s == 0; }));
    assert(codec.microphone_frame_[0] == 0);
    const unsigned before = codec.hardware_reads;
    assert(codec.Read(fresh.data(), fresh.size()) == 0);
    assert(codec.hardware_reads == before);
}
'''
    cpp = tmp_path / "queued_pdm.cc"
    exe = tmp_path / "queued_pdm"
    cpp.write_text(
        preamble + "int SenseReferenceCodec::Read(" + _read() + exercise,
        encoding="utf-8",
    )
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pthread",
         str(cpp), "-o", str(exe)],
        check=True, timeout=25,
    )
    subprocess.run([str(exe)], check=True, timeout=10)
