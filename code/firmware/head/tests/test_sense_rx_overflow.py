"""Host C++ regression for Sense I2S RX DMA queue overflow telemetry."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

HEAD = Path(__file__).resolve().parents[1]
CODEC_H = HEAD / "sense/sense_reference_codec.h"
CODEC_CC = HEAD / "sense/sense_reference_codec.cc"


def test_rx_queue_overflow_isr_latches_integrity_and_invalidates_bench_window(tmp_path):
    """Overflow injection before a full Read() must still fail integrity and capture."""
    compiler = shutil.which(os.environ.get("CXX", "c++"))
    if compiler is None:
        pytest.skip("C++ compiler unavailable")

    codec_src = CODEC_CC.read_text(encoding="utf-8")
    isr_method = (
        "void IRAM_ATTR SenseReferenceCodec::RecordRxQueueOverflowFromIsr("
        + codec_src.split(
            "void IRAM_ATTR SenseReferenceCodec::RecordRxQueueOverflowFromIsr(", 1
        )[1].split("bool IRAM_ATTR SenseReferenceCodec::OnRxQueueOverflowIsr(", 1)[0]
    )
    read_method = "int SenseReferenceCodec::Read(" + codec_src.split(
        "int SenseReferenceCodec::Read(", 1
    )[1].split("int SenseReferenceCodec::Write(", 1)[0]
    diag_method = (
        "SenseReferenceCodec::ReferenceDiagnostics\n"
        "SenseReferenceCodec::GetReferenceDiagnostics("
        + codec_src.split("SenseReferenceCodec::GetReferenceDiagnostics(", 1)[1].split(
            "void SenseReferenceCodec::EnableOutput(", 1
        )[0]
    )

    cpp = tmp_path / "rx_overflow_test.cc"
    exe = tmp_path / "rx_overflow_test"
    cpp.write_text(
        r"""
#include <algorithm>
#include <array>
#include <atomic>
#include <cassert>
#include <cstdint>
#include <mutex>
#define IRAM_ATTR
#define ESP_LOGW(...) ((void)0)
int64_t esp_timer_get_time() { return 50000; }

struct NoAudioCodecSimplexPdm {
    int Read(int16_t* dest, int frames) {
        // Returns a complete valid frame even though an earlier DMA overflow occurred.
        std::fill_n(dest, frames, 77);
        return frames;
    }
};

struct FakeBenchWindow {
    bool invalidated = false;
    bool offering = false;
    bool ready() const { return false; }
    bool failed() const { return invalidated; }
    uint32_t frames_received() const { return 1; }
    int64_t first_sample_us() const { return 1; }
    int64_t last_sample_us() const { return 1; }
    void invalidate_read(int64_t) { invalidated = true; }
    void offer(const int16_t*, const int16_t*, uint32_t, int64_t, bool) {
        offering = true;
    }
};

struct FakeSpeakerActivity {
    using Snapshot = int;
    void FenceWindowStart(Snapshot&, int64_t) {}
    bool AdvancedSince(Snapshot&, int64_t) { return false; }
    void EndWindow(Snapshot&) {}
};

class SenseReferenceCodec : public NoAudioCodecSimplexPdm {
public:
    static constexpr int kMicRate = 16000;
    static constexpr int kMaxReadFrames = 2048;
    int input_sample_rate_ = kMicRate;
    struct ReferenceDiagnostics {
        uint32_t underflow_reads;
        uint32_t overwrite_reads;
        uint32_t discarded_stale_writes;
        uint32_t short_output_writes;
        uint32_t short_input_reads;
        uint32_t microphone_frames_read;
        uint32_t speaker_frames_accepted;
        bool microphone_privacy_muted;
        uint32_t microphone_privacy_epoch;
        bool integrity_failed;
        uint32_t rx_queue_overflows;
        uint32_t rx_queue_overflow_bytes;
    };
    ReferenceDiagnostics GetReferenceDiagnostics();
    void RecordRxQueueOverflowFromIsr(size_t dropped_bytes) noexcept;
    int Read(int16_t* dest, int samples);
    std::atomic<bool> microphone_privacy_muted_{false};
    std::atomic<uint32_t> microphone_privacy_epoch_{0};
    std::mutex input_read_mutex_, reference_mutex_, bench_mutex_;
    std::array<int16_t, kMaxReadFrames> microphone_frame_{}, reference_frame_{};
    FakeBenchWindow bench_window_{};
    FakeSpeakerActivity speaker_activity_{};
    FakeSpeakerActivity::Snapshot bench_speaker_at_start_{};
    bool bench_speaker_activity_in_window_ = false;
    uint32_t missing_reference_reads_ = 0;
    uint32_t reference_overwrite_reads_ = 0;
    uint32_t stale_publish_discards_ = 0;
    uint32_t short_output_writes_ = 0;
    uint32_t short_input_reads_ = 0;
    uint32_t microphone_frames_read_ = 0;
    uint32_t speaker_frames_accepted_ = 0;
    uint32_t consecutive_missing_reference_reads_ = 0;
    std::atomic<uint32_t> rx_queue_overflows_{0};
    std::atomic<uint32_t> rx_queue_overflow_bytes_{0};
    std::atomic<bool> bench_contention_fault_{false};
    uint32_t observed_rx_queue_overflows_ = 0;
    bool reference_integrity_failed_ = false;
    void ApplyPendingBenchContentionFaultLocked(int64_t now_us) {
        if (bench_contention_fault_.exchange(false, std::memory_order_acq_rel)) {
            bench_window_.invalidate_read(now_us);
        }
    }
    void FillSilenceLocked(int64_t) {}
    bool ReadReferenceLocked(int16_t* dest, int frames, int64_t) {
        std::fill_n(dest, frames, 12);
        return true;
    }
};
#define CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED 1
"""
        + isr_method
        + read_method
        + diag_method
        + r"""
int main() {
    SenseReferenceCodec codec;
    std::array<int16_t, 64> out{};
    assert(codec.Read(out.data(), static_cast<int>(out.size())) == 64);
    auto clean = codec.GetReferenceDiagnostics();
    assert(clean.rx_queue_overflows == 0 && clean.rx_queue_overflow_bytes == 0);
    assert(!clean.integrity_failed);
    assert(!codec.bench_window_.invalidated && codec.bench_window_.offering);

    // Inject DMA queue overflow from ISR context and verify diagnostics immediately
    // fail closed, and subsequent full-frame Read() latches failure & drops capture.
    codec.bench_window_.offering = false;
    codec.RecordRxQueueOverflowFromIsr(512);
    codec.RecordRxQueueOverflowFromIsr(256);
    auto before_read = codec.GetReferenceDiagnostics();
    assert(before_read.rx_queue_overflows == 2);
    assert(before_read.rx_queue_overflow_bytes == 768);
    assert(before_read.integrity_failed);

    assert(codec.Read(out.data(), static_cast<int>(out.size())) == 64);
    auto after_read = codec.GetReferenceDiagnostics();
    assert(after_read.short_input_reads == 0);
    assert(after_read.rx_queue_overflows == 2);
    assert(after_read.rx_queue_overflow_bytes == 768);
    assert(after_read.integrity_failed);
    assert(codec.reference_integrity_failed_);
    assert(codec.bench_window_.invalidated);
    assert(!codec.bench_window_.offering);
    return 0;
}
""",
        encoding="utf-8",
    )
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(exe)],
        check=True,
        timeout=30,
    )
    subprocess.run([str(exe)], check=True, timeout=10)
