"""The physical BOOT mute must run on press, not after release.

Source contracts are not a substitute for the actual on-head held-button PCM
and Opus leakage test. Xiaozhi's pinned OnClick event follows release.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "sense" / "desk_robot_sense.cc"


def _callbacks():
    source = SOURCE.read_text()
    assert "std::atomic<bool> boot_press_muted_{false};" in source
    assert "boot_button_.OnPressDown([this]() {" in source
    press = source.split("boot_button_.OnPressDown([this]() {", 1)[1].split(
        "boot_button_.OnClick([this]() {", 1
    )[0]
    click = source.split("boot_button_.OnClick([this]() {", 1)[1].split(
        "void StartNetwork() override", 1
    )[0]
    return press, click


def test_boot_press_gates_real_pdm_and_opus_before_release_or_network_abort():
    press, _ = _callbacks()
    expected = (
        "audio_operator_touched_.store(true, std::memory_order_release);",
        "audio_operator_muted_.exchange(",
        "boot_press_muted_.store(!already_muted, std::memory_order_release);",
        "app.SetSenseMicrophonePrivacyMuted(true);",
        "->SetMicrophonePrivacyMuted(true);",
        "app.StopListening();",
    )
    for phrase in expected:
        assert phrase in press
    assert press.index(expected[0]) < press.index(expected[1])
    assert press.index(expected[3]) < press.index(expected[4])
    assert press.index(expected[4]) < press.index(expected[5])


def test_boot_release_does_not_reverse_press_mute_and_second_tap_can_unmute():
    press, click = _callbacks()
    assert "if (already_muted) return;" in press
    assert "boot_press_muted_.exchange(false, std::memory_order_acq_rel)" in click
    assert click.index("boot_press_muted_.exchange(false") < click.index(
        "const bool now_muted = !audio_operator_muted_.load("
    )
    assert "app.SetSenseMicrophonePrivacyMuted(now_muted);" in click
    assert "->SetMicrophonePrivacyMuted(now_muted);" in click
    assert "if (state == kDeviceStateIdle) app.ToggleChatState();" in click
    assert "if (state == kDeviceStateStarting)" in click
    assert click.index("if (state == kDeviceStateStarting)") < click.index(
        "boot_press_muted_.exchange(false"
    )


def test_boot_long_hold_is_privacy_action_even_without_click_or_long_press():
    press, click = _callbacks()
    assert "app.StopListening();" in press
    assert "boot_button_.OnLongPress([this]() { boot_privacy_gesture_.Cancel(); });" in press
    assert "if (boot_press_muted_.exchange(false" in click


def test_boot_click_requires_fresh_released_gesture_and_high_gpio():
    press, click = _callbacks()
    assert press.index("boot_privacy_gesture_.PressDown()") < press.index(
        "audio_operator_muted_.exchange("
    )
    assert "boot_button_.OnPressUp([this]() { boot_privacy_gesture_.PressUp(); });" in press
    assert "boot_button_.OnDoubleClick([this]() { boot_privacy_gesture_.Cancel(); });" in press
    assert click.index("boot_privacy_gesture_.TakeClick()") < click.index(
        "app.SetSenseMicrophonePrivacyMuted(now_muted);"
    )
    assert "gpio_get_level(BOOT_BUTTON_GPIO) == 0" in click


def test_boot_privacy_gesture_native_adversarial(tmp_path):
    compiler = shutil.which("c++")
    if not compiler:
        pytest.skip("native C++ compiler unavailable")
    source = SOURCE.read_text().split("class BootPrivacyGesture {", 1)[1]
    gesture = "class BootPrivacyGesture {" + source.split("\n};", 1)[0] + "\n};\n"
    cpp = tmp_path / "gesture.cc"
    exe = tmp_path / "gesture"
    cpp.write_text(gesture + """
#include <cassert>
int main() {
    BootPrivacyGesture g;
    assert(!g.Held());
    assert(!g.TakeClick());
    g.PressUp(); assert(!g.Held()); assert(!g.TakeClick());
    assert(g.PressDown()); assert(g.Held()); assert(!g.TakeClick());
    g.PressUp(); assert(!g.Held()); assert(g.TakeClick()); assert(!g.TakeClick());
    assert(g.PressDown()); assert(g.Held()); assert(!g.PressDown());
    assert(!g.Held()); g.PressUp(); assert(!g.TakeClick());
    assert(g.PressDown()); assert(g.Held()); g.Cancel(); assert(!g.Held());
    g.PressUp(); assert(!g.TakeClick());
    assert(g.PressDown()); assert(g.Held()); g.PressUp(); assert(g.TakeClick());
    assert(g.PressDown()); g.PressUp(); g.PressUp(); assert(!g.TakeClick());
    assert(g.PressDown()); g.PressUp(); g.Cancel(); assert(!g.TakeClick());
    // A cancelled hold cannot grant bench consent until a fresh press.
    g.Cancel(); assert(!g.Held());
    assert(g.PressDown()); assert(g.Held()); g.PressUp(); assert(!g.Held());
    assert(g.PressDown()); assert(g.Held()); assert(!g.TakeClick());
    g.Cancel(); assert(!g.Held()); g.PressUp(); assert(!g.TakeClick());
    for (int i=0;i<100000;++i) {
        assert(g.PressDown()); assert(!g.PressDown()); g.PressUp(); assert(!g.TakeClick());
        assert(g.PressDown()); g.PressUp(); assert(g.TakeClick());
    }
}
""", encoding="utf-8")
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(exe)],
        check=True, timeout=25,
    )
    subprocess.run([str(exe)], check=True, timeout=5)


def test_bench_pcm_requires_distinct_physical_gesture_and_one_use_grant(tmp_path):
    head = SOURCE.parents[1]
    board = SOURCE.read_text()
    codec = (head / "sense/sense_reference_codec.cc").read_text()
    header = (head / "sense/sense_reference_codec.h").read_text()
    press, click = _callbacks()
    assert "boot_privacy_gesture_.Held()" in press
    assert "!boot_press_muted_.load(" in press
    assert "bench_hold_consent_.Grant(esp_timer_get_time())" in press
    assert "bench_hold_consent_.Take(esp_timer_get_time())" in click
    assert "held && !now_muted && state == kDeviceStateIdle" in click
    assert board.count("->GrantBenchPcmConsent()") == 1
    assert "WIFI_EVENT_STA_DISCONNECTED || event == WIFI_EVENT_STA_STOP" in board
    assert "static_cast<DeskRobotSenseBoard*>(context)->RevokeBenchConsent()" in board
    assert "board->RevokeBenchConsent();" in board
    begin = codec.split("bool SenseReferenceCodec::BeginBenchPcmCapture(", 1)[1]
    begin = begin.split("SenseReferenceCodec::BenchCaptureProgress", 1)[0]
    assert begin.index("bench_consent_.Take(") < begin.index("heap_caps_malloc(")
    assert "if (revoke_consent) bench_consent_.Revoke();" in codec
    assert "if (muted) AbortBenchPcmCapture();" in header

    compiler = shutil.which("c++")
    if not compiler:
        pytest.skip("native C++ compiler unavailable")
    cpp = tmp_path / "bench_consent.cc"
    exe = tmp_path / "bench_consent"
    cpp.write_text(r'''
#include "sense_pcm_window.h"
#include <cassert>
#include <limits>
int main() {
    desk_robot::FreshBenchPcmConsent consent;
    assert(!consent.Take(1));
    consent.Grant(0); assert(!consent.Take(1));
    consent.Grant(100); assert(!consent.Take(99)); assert(!consent.Take(100));
    consent.Grant(100); assert(consent.Take(100)); assert(!consent.Take(101));
    consent.Grant(100); assert(consent.Take(30'000'100));
    consent.Grant(100); assert(!consent.Take(30'000'101));
    consent.Grant(100); consent.Revoke(); assert(!consent.Take(100));
    const auto high = std::numeric_limits<std::int64_t>::max();
    consent.Grant(high - 10); assert(consent.Take(high));
    consent.Grant(1); assert(!consent.Take(high));
}
''', encoding="utf-8")
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
         "-I", str(head / "sense"), str(cpp), "-o", str(exe)],
        check=True, timeout=25,
    )
    subprocess.run([str(exe)], check=True, timeout=5)


def test_native_bench_start_runs_real_codec_with_fault_injection(tmp_path):
    """Exercise the actual grant, START and abort bodies with mocked I/O only."""
    compiler = shutil.which("c++")
    if not compiler:
        pytest.skip("native C++ compiler unavailable")
    head = SOURCE.parents[1]
    codec = (head / "sense/sense_reference_codec.cc").read_text()
    start = codec.split("void SenseReferenceCodec::GrantBenchPcmConsent()", 1)[1]
    start = "void SenseReferenceCodec::GrantBenchPcmConsent()" + start.split(
        "SenseReferenceCodec::BenchCaptureProgress", 1
    )[0]
    abort = codec.split("void SenseReferenceCodec::AbortBenchPcmCapture(", 1)[1]
    abort = "void SenseReferenceCodec::AbortBenchPcmCapture(" + abort.split("#endif", 1)[0]
    preamble = r'''
#include "sense_pcm_window.h"
#include <algorithm>
#include <atomic>
#include <cassert>
#include <cstdlib>
#include <functional>
#include <mutex>
#include <cstdint>
static int64_t now_us = 100;
static bool fail_alloc = false, fail_timer = false;
static unsigned allocations = 0;
static std::function<void()> during_allocation;
constexpr int ESP_OK = 0, MALLOC_CAP_SPIRAM = 1, MALLOC_CAP_8BIT = 2;
using esp_timer_handle_t = void*;
struct esp_timer_create_args_t {
    void (*callback)(void*);
    void* arg;
    const char* name;
};
int64_t esp_timer_get_time() { return now_us; }
int esp_timer_create(const esp_timer_create_args_t*, esp_timer_handle_t* handle) {
    *handle = reinterpret_cast<void*>(1); return ESP_OK;
}
int esp_timer_stop(esp_timer_handle_t) { return ESP_OK; }
int esp_timer_start_once(esp_timer_handle_t, int64_t) { return fail_timer ? -1 : ESP_OK; }
void* heap_caps_malloc(size_t n, int) {
    ++allocations;
    if (during_allocation) during_allocation();
    return fail_alloc ? nullptr : std::malloc(n);
}
struct SenseReferenceCodec {
    std::mutex bench_mutex_, reference_mutex_;
    std::atomic<bool> microphone_privacy_muted_{false};
    std::atomic<uint32_t> microphone_privacy_epoch_{7};
    std::atomic<uint64_t> bench_capture_generation_{0};
    desk_robot::FreshBenchPcmConsent bench_consent_;
    desk_robot::SensePcmWindow bench_window_;
    bool bench_start_pending_ = false;
    bool bench_transfer_active_ = false, bench_speaker_activity_in_window_ = false;
    esp_timer_handle_t bench_expiry_timer_ = nullptr;
    int64_t bench_started_us_ = 0;
    int bench_speaker_at_start_ = 0;
    struct SpeakerActivity {
        int BeginWindow() { return 1; }
        void EndWindow(int) {}
    } speaker_activity_;
    static void BenchPcmExpiry(void*) {}
    static void ReleaseBenchPcmCapture(int16_t* p) { std::free(p); }
    void GrantBenchPcmConsent();
    bool BeginBenchPcmCapture(uint32_t expected_privacy_epoch);
    void AbortBenchPcmCapture(bool revoke_consent = true);
};
'''
    exercise = r'''
int main() {
    SenseReferenceCodec codec;
    assert(!codec.BeginBenchPcmCapture(7) && allocations == 0);
    codec.GrantBenchPcmConsent();
    assert(!codec.BeginBenchPcmCapture(6) && allocations == 0);
    codec.AbortBenchPcmCapture(false);
    assert(codec.BeginBenchPcmCapture(7) && allocations == 1);
    codec.AbortBenchPcmCapture();
    assert(!codec.BeginBenchPcmCapture(7) && allocations == 1);
    codec.GrantBenchPcmConsent();
    fail_alloc = true;
    assert(!codec.BeginBenchPcmCapture(7) && allocations == 2);
    fail_alloc = false;
    assert(!codec.BeginBenchPcmCapture(7) && allocations == 2);
    codec.GrantBenchPcmConsent();
    fail_timer = true;
    assert(!codec.BeginBenchPcmCapture(7) && !codec.bench_window_.occupied());
    fail_timer = false;
    assert(!codec.BeginBenchPcmCapture(7));
    codec.GrantBenchPcmConsent();
    codec.AbortBenchPcmCapture();
    assert(!codec.BeginBenchPcmCapture(7));
    codec.GrantBenchPcmConsent();
    during_allocation = [&] { codec.microphone_privacy_epoch_.fetch_add(2); };
    assert(!codec.BeginBenchPcmCapture(7) && !codec.bench_window_.occupied());
    during_allocation = {};
    assert(!codec.BeginBenchPcmCapture(9));
    codec.microphone_privacy_muted_.store(true);
    codec.GrantBenchPcmConsent();
    codec.microphone_privacy_muted_.store(false);
    assert(!codec.BeginBenchPcmCapture(9));
    codec.GrantBenchPcmConsent();
    now_us += 30'000'001;
    assert(!codec.BeginBenchPcmCapture(9));
    codec.GrantBenchPcmConsent();
    assert(codec.BeginBenchPcmCapture(9));
    codec.AbortBenchPcmCapture();
    assert(!codec.bench_window_.occupied());
}
'''
    cpp = tmp_path / "bench_start.cc"
    exe = tmp_path / "bench_start"
    cpp.write_text(preamble + start + abort + exercise, encoding="utf-8")
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pthread",
         "-I", str(head / "sense"), str(cpp), "-o", str(exe)],
        check=True, timeout=25,
    )
    subprocess.run([str(exe)], check=True, timeout=5)
