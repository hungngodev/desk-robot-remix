"""The optional calibration allocator must not hold the realtime PDM mutex."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HEAD = Path(__file__).resolve().parents[1]


def test_bench_start_allocation_yields_and_cancellation_fences(tmp_path: Path) -> None:
    compiler = shutil.which("g++") or shutil.which("clang++")
    if compiler is None:
        pytest.skip("Native C++ compiler unavailable")
    codec = (HEAD / "sense/sense_reference_codec.cc").read_text()
    starter = "bool SenseReferenceCodec::BeginBenchPcmCapture("
    begin = starter + codec.split(starter, 1)[1].split(
        "SenseReferenceCodec::BenchCaptureProgress", 1
    )[0]
    release_marker = "void SenseReferenceCodec::ReleaseBenchPcmCapture("
    release = release_marker + codec.split(release_marker, 1)[1].split("\n}\n", 1)[0] + "\n}\n"
    abort_marker = "void SenseReferenceCodec::AbortBenchPcmCapture("
    abort = abort_marker + codec.split(abort_marker, 1)[1].split("\n#endif", 1)[0]
    source = tmp_path / "bench_start.cc"
    source.write_text(PREFIX + release + begin + abort + SUFFIX)
    binary = tmp_path / "bench_start"
    pie_flags = [] if sys.platform == "darwin" else ["-fno-pie", "-no-pie"]
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"} if sys.platform == "darwin" else None
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pthread",
         "-fsanitize=address,undefined", *pie_flags, str(source), "-o", str(binary)],
        check=True, capture_output=True, text=True, env=env, timeout=60,
    )
    subprocess.run([str(binary)], check=True, env=env, timeout=10)


PREFIX = r"""
#include <algorithm>
#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <functional>
#include <mutex>
#include <thread>
#include <utility>
namespace desk_robot {
struct SensePcmWindow {
    static constexpr size_t kFrames = 64000, kBytes = kFrames * 4;
    int16_t* data = nullptr;
    bool occupied() const { return data != nullptr; }
    bool begin(int16_t* storage, int64_t) { data = storage; return true; }
    int16_t* discard() { return std::exchange(data, nullptr); }
};
}
constexpr int ESP_OK = 0, MALLOC_CAP_SPIRAM = 1, MALLOC_CAP_8BIT = 2;
struct esp_timer_create_args_t { void (*callback)(void*); void* arg; const char* name; };
int esp_timer_create(esp_timer_create_args_t*, void** timer) { *timer = timer; return ESP_OK; }
int esp_timer_stop(void*) { return ESP_OK; }
bool fail_timer = false, fail_alloc = false;
int timer_starts = 0;
int esp_timer_start_once(void* timer, int64_t delay_us) {
    assert(timer != nullptr && delay_us == 12'000'000);
    ++timer_starts;
    return fail_timer ? -1 : ESP_OK;
}
int64_t esp_timer_get_time() { return 100; }
std::function<void()> allocation_hook, free_hook;
int allocations = 0, frees = 0;
void* heap_caps_malloc(size_t bytes, int caps) {
    assert(caps == (MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    assert(bytes == desk_robot::SensePcmWindow::kBytes);
    if (auto hook = std::exchange(allocation_hook, {})) hook();
    if (fail_alloc) return nullptr;
    auto* data = static_cast<uint8_t*>(std::malloc(bytes));
    assert(data != nullptr);
    std::fill_n(data, bytes, 0xa5);
    ++allocations;
    return data;
}
void heap_caps_free(void* p) {
    if (free_hook) free_hook();
    auto* bytes = static_cast<uint8_t*>(p);
    for (size_t i = 0; i < desk_robot::SensePcmWindow::kBytes; ++i) assert(bytes[i] == 0);
    ++frees;
    std::free(p);
}
struct Consent {
    bool grant = true;
    bool Take(int64_t) { return std::exchange(grant, false); }
    void Revoke() { grant = false; }
};
struct Activity {
    int BeginWindow() { return 1; }
    void EndWindow(int) {}
};
struct SenseReferenceCodec {
    std::mutex bench_mutex_, reference_mutex_;
    std::atomic<bool> microphone_privacy_muted_{false};
    std::atomic<uint32_t> microphone_privacy_epoch_{1};
    std::atomic<uint64_t> bench_capture_generation_{0};
    std::atomic<bool> bench_contention_fault_{false};
    bool bench_transfer_active_ = false, bench_start_pending_ = false;
    desk_robot::SensePcmWindow bench_window_;
    Consent bench_consent_;
    Activity speaker_activity_;
    int bench_speaker_at_start_ = 0;
    bool bench_speaker_activity_in_window_ = false;
    int64_t bench_started_us_ = 0;
    void* bench_expiry_timer_ = nullptr;
    static void BenchPcmExpiry(void*) {}
    static void ReleaseBenchPcmCapture(int16_t*);
    void ApplyPendingBenchContentionFaultLocked(int64_t) {}
    bool BeginBenchPcmCapture(uint32_t);
    void AbortBenchPcmCapture(bool);
};
void while_unlocked(SenseReferenceCodec& codec, const std::function<void()>& action) {
    bool acquired = false;
    std::thread other([&] {
        acquired = codec.bench_mutex_.try_lock();
        if (acquired) {
            codec.bench_mutex_.unlock();
            action();
        }
    });
    other.join();
    assert(acquired);
}
"""

SUFFIX = r"""
int main() {
    SenseReferenceCodec codec;
    free_hook = [&] { while_unlocked(codec, [] {}); };
    allocation_hook = [&] { while_unlocked(codec, [] {}); };
    assert(codec.BeginBenchPcmCapture(1));
    assert(codec.bench_window_.occupied() && !codec.bench_start_pending_);
    assert(timer_starts == 1 && allocations == 1 && frees == 0);
    auto* samples = codec.bench_window_.data;
    const auto sample_count = desk_robot::SensePcmWindow::kFrames * 2;
    assert(std::all_of(samples, samples + sample_count, [](int16_t x) { return x == 0; }));
    // Simulate captured private PCM so skipping the wipe cannot pass on zeroed RAM.
    std::fill_n(samples, sample_count, 1234);
    codec.AbortBenchPcmCapture(true);
    assert(!codec.bench_window_.occupied() && allocations == 1 && frees == 1);

    codec.bench_consent_.grant = true;
    allocation_hook = [&] { while_unlocked(codec, [&] { codec.AbortBenchPcmCapture(false); }); };
    assert(!codec.BeginBenchPcmCapture(1));
    assert(!codec.bench_window_.occupied() && !codec.bench_start_pending_);
    assert(!codec.BeginBenchPcmCapture(1));  // Consumed even on cancellation.

    codec.bench_consent_.grant = true;
    allocation_hook = [&] {
        while_unlocked(codec, [&] {
            codec.microphone_privacy_epoch_.fetch_add(1);
        });
    };
    assert(!codec.BeginBenchPcmCapture(1));
    assert(!codec.bench_window_.occupied() && !codec.bench_start_pending_);

    codec.bench_consent_.grant = true;
    allocation_hook = [&] {
        while_unlocked(codec, [&] {
            codec.bench_consent_.grant = true;
            assert(!codec.BeginBenchPcmCapture(2));
        });
    };
    assert(codec.BeginBenchPcmCapture(2));
    codec.AbortBenchPcmCapture(true);
    assert(!codec.bench_start_pending_);

    codec.bench_consent_.grant = true;
    fail_timer = true;
    assert(!codec.BeginBenchPcmCapture(2));
    assert(!codec.bench_window_.occupied() && !codec.bench_start_pending_);
    fail_timer = false;
    codec.bench_consent_.grant = true;
    fail_alloc = true;
    assert(!codec.BeginBenchPcmCapture(2));
    assert(!codec.bench_window_.occupied() && !codec.bench_start_pending_);
    // Only the two successful STARTs and the timer-failure path arm expiry.
    assert(timer_starts == 3);
    assert(allocations == 5 && frees == 5);
}
"""
