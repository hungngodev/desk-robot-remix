"""Exercise the Sense OLED flush hook with synchronous I2C failure injection."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

OVERLAY = Path(__file__).resolve().parents[1] / "overlay"


def test_synchronous_oled_flush_failure_recovers_current_frame(tmp_path):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("Native C++ compiler unavailable")
    (tmp_path / "esp_lcd_panel_interface.h").write_text(r"""
#pragma once
using esp_err_t = int;
constexpr esp_err_t ESP_OK = 0, ESP_ERR_INVALID_STATE = 1, ESP_ERR_TIMEOUT = 2;
struct esp_lcd_panel_t {
    esp_err_t (*draw_bitmap)(esp_lcd_panel_t*, int, int, int, int, const void*);
    void* user_data = nullptr;
};
""")
    (tmp_path / "lvgl.h").write_text(r"""
#pragma once
#include <cassert>
struct lv_obj_t { int invalidations = 0; };
struct lv_display_t { lv_obj_t screen; bool flushing = false; int completions = 0; };
inline lv_display_t display;
inline lv_display_t* lv_display_get_default() { return &display; }
inline lv_obj_t* lv_display_get_screen_active(lv_display_t* d) { return &d->screen; }
inline void lv_display_flush_ready(lv_display_t* d) {
    assert(d->flushing);  // exactly one completion, even on failure
    d->flushing = false;
    ++d->completions;
}
inline void lv_obj_invalidate(lv_obj_t* screen) { ++screen->invalidations; }
""")
    source = tmp_path / "panel.cc"
    binary = tmp_path / "panel"
    source.write_text(r"""
#include "face_panel_flush.hpp"
#include <array>
#include <cassert>
using desk_robot::FacePanelFlushRecovery;
using Frame = std::array<unsigned char, 1024>;
Frame panel_pixels{};
bool fail = false;
int transfers = 0;

esp_err_t Transfer(esp_lcd_panel_t*, int, int, int x2, int y2, const void* pixels) {
    ++transfers;
    const auto& frame = *static_cast<const Frame*>(pixels);
    if (fail) {
        // Simulate a bus error after the first page, with NO completion callback.
        for (int i = 0; i < 128; ++i) panel_pixels[i] = frame[i];
        return ESP_ERR_TIMEOUT;
    }
    if (x2 == 128 && y2 == 64) panel_pixels = frame;
    lv_display_flush_ready(&display);  // existing ESP-IDF success callback
    return ESP_OK;
}

int main() {
    FacePanelFlushRecovery recovery;
    esp_lcd_panel_t panel{Transfer};
    assert(recovery.Install(&panel, 128, 64) == ESP_OK);
    assert(recovery.Install(&panel, 128, 64) == ESP_ERR_INVALID_STATE);
    Frame subtitle{}, fault{};
    subtitle.fill(1);
    fault.fill(2);
    auto draw = [&](const Frame& frame, int height = 64) {
        assert(!display.flushing);
        display.flushing = true;
        return panel.draw_bitmap(&panel, 0, 0, 128, height, &frame);
    };
    assert(draw(subtitle) == ESP_OK);
    assert(panel_pixels == subtitle && display.completions == 1);
    fail = true;
    assert(draw(fault) == ESP_ERR_TIMEOUT);
    assert(!display.flushing && display.completions == 2);
    assert(panel_pixels[0] == 2 && panel_pixels[128] == 1);
    recovery.Retry(100);
    recovery.Retry(101);
    recovery.Retry(1099);
    assert(display.screen.invalidations == 1 && transfers == 2);
    assert(draw(fault) == ESP_ERR_TIMEOUT);
    recovery.Retry(1100);
    assert(display.screen.invalidations == 2 && display.completions == 3);
    // A partial success is not a full repair. Another full redraw is needed.
    fail = false;
    assert(draw(fault, 8) == ESP_OK);
    recovery.Retry(2100);
    assert(display.screen.invalidations == 3);
    // New subtitle pixels have arrived while the fault status is still active.
    // The retry invalidates current UI rather than keeping the old frame pointer.
    fault[512] = 3;
    assert(draw(fault) == ESP_OK);
    assert(panel_pixels == fault && display.completions == 5);
    recovery.Retry(3100);
    assert(display.screen.invalidations == 3);
    assert(!display.flushing && transfers == 5);
}
""")
    pie_flags = [] if sys.platform == "darwin" else ["-fno-pie", "-no-pie"]
    env = dict(os.environ, UBSAN_OPTIONS="halt_on_error=1", ASAN_OPTIONS="halt_on_error=1")
    subprocess.run(
        [
            compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
            "-fsanitize=address,undefined", *pie_flags,
            "-I", str(tmp_path), "-I", str(OVERLAY), str(source), "-o", str(binary),
        ],
        check=True, timeout=60, env=env,
    )
    subprocess.run([str(binary)], check=True, timeout=30, env=env)
