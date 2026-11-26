"""Protect audio maintenance from a stalled cosmetic OLED refresh."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BOARD = Path(__file__).resolve().parents[1] / "sense" / "desk_robot_sense.cc"


def test_face_render_guard_releases_only_acquired_lock(tmp_path):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("Native C++ compiler unavailable")
    guard = BOARD.read_text().split("class FaceRenderGuard {", 1)[1].split("\n};", 1)[0]
    source = tmp_path / "guard.cc"
    binary = tmp_path / "guard"
    source.write_text(
        r"""
#include <cassert>
#include <cstdint>
#include <type_traits>
static bool available = false;
static unsigned attempts = 0, releases = 0;
static bool lvgl_port_lock(uint32_t timeout_ms) {
    assert(timeout_ms == 1);
    ++attempts;
    return available;
}
static void lvgl_port_unlock() { ++releases; }
class FaceRenderGuard {""" + guard + r"""
};
int main() {
    static_assert(!std::is_copy_constructible_v<FaceRenderGuard>);
    for (unsigned i = 0; i < 100; ++i) {
        { FaceRenderGuard guard; assert(!guard); }
    }
    assert(attempts == 100 && releases == 0);
    available = true;
    { FaceRenderGuard guard; assert(guard); assert(releases == 0); }
    assert(attempts == 101 && releases == 1);
}
"""
    )
    pie_flags = [] if sys.platform == "darwin" else ["-fno-pie", "-no-pie"]
    env = dict(os.environ, ASAN_OPTIONS="halt_on_error=1", UBSAN_OPTIONS="halt_on_error=1")
    subprocess.run(
        [
            compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
            "-fsanitize=address,undefined", *pie_flags, str(source), "-o", str(binary),
        ],
        check=True, timeout=30, env=env,
    )
    subprocess.run([str(binary)], check=True, timeout=10, env=env)


def test_face_task_skips_contended_frame_after_audio_maintenance():
    board = BOARD.read_text()
    face = board.split("static void FaceTask(void* context)", 1)[1].split(
        "void InitializeDisplay()", 1
    )[0]
    assert face.index("app.ToggleChatState();") < face.index("FaceRenderGuard render_lock;")
    rejected, accepted = face.split("if (!render_lock) {", 1)[1].split("} else {", 1)
    assert "last_face_available = false;" in rejected
    assert "model_mood_active = false;" in rejected
    assert "Motion::kNone, false" in rejected
    assert "SetLocalStatus" not in rejected
    assert "SetEmotion" not in rejected
    assert "ShowEyes" not in rejected
    assert "vTaskDelay" not in rejected
    assert accepted.index("SetLocalStatus(local_status)") < accepted.index("ShowEyes(eyes)")
    assert "last_priority_active = priority_active;" in accepted
    assert "last_face_available = face_available;" in accepted
    assert "\n            }\n            vTaskDelay(pdMS_TO_TICKS(100));" in accepted
    assert "PollInteraction()" not in face


def test_oled_i2c_transfer_has_finite_timeout():
    display = BOARD.read_text().split("void InitializeDisplay()", 1)[1].split(
        "void InitializeCamera()", 1
    )[0]
    assert "io_config.scl_speed_hz = 400000;" in display
    assert "io_config.transaction_timeout_ms = 50;" in display
    assert display.index("transaction_timeout_ms") < display.index("esp_lcd_new_panel_io_i2c")
