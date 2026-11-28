"""Host monochrome footprint of the local aperture overlay (not stock glyphs)."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

OVERLAY = Path(__file__).resolve().parents[1] / "overlay"


def test_all_expression_aperture_transitions(tmp_path):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("Native C++ compiler unavailable")
    source = tmp_path / "face_bounds.cc"
    binary = tmp_path / "face_bounds"
    source.write_text(r"""
#include "face_eye_geometry.hpp"
#include "face_mood_morph.hpp"
#include <array>
#include <cassert>
#include <string_view>
#include <set>
#include <tuple>
using namespace desk_robot::face_eye_geometry;
using desk_robot::FaceMoodMorph;

struct Expression { std::string_view name; int aperture; };
// Xiaozhi Noto emoji names: neutral plus twenty emotional expressions.
// Zero means the local morph must yield to the stock glyph.
constexpr Expression expressions[] = {
    {"neutral", 10}, {"happy", 8}, {"laughing", 0}, {"funny", 0},
    {"sad", 6}, {"angry", 5}, {"crying", 0}, {"loving", 0},
    {"embarrassed", 0}, {"surprised", 14}, {"shocked", 0}, {"thinking", 9},
    {"winking", 0}, {"cool", 0}, {"relaxed", 0}, {"delicious", 0},
    {"kissy", 0}, {"confident", 0}, {"sleepy", 2}, {"silly", 0}, {"confused", 0},
};
static_assert(sizeof(expressions) / sizeof(expressions[0]) == 21);
using Framebuffer = std::array<bool, 128 * 64>;

static void Paint(Framebuffer& pixels, int x, int y, int w, int h, bool ink) {
    assert(w > 0 && h > 0);
    assert(x >= 48 && x + w <= 80 && y >= 16 && y + h <= 64);
    for (int row = y; row < y + h; ++row)
        for (int col = x; col < x + w; ++col)
            pixels.at(static_cast<size_t>(row) * 128 + col) = ink;
}

// Rectangular footprint of the eye geometry; the real renderer rounds corners.
// Do not paint the white layer as ink: that would hide eye and pupil regressions.
static void CheckFrame(int height, int x, int y, bool blink) {
    static std::set<std::tuple<int, int, int, bool>> checked;
    if (!checked.emplace(height, x, y, blink).second) return;
    Framebuffer pixels{};
    if (blink) height = kClosedHeight;
    if (height != 0) {
        for (int eye = 0; eye < kEyeCount; ++eye) {
            const int left = (kPanelWidth - kSlotWidth) / 2 + EyeX(eye);
            const int top = kStatusHeight + EyeY(height);
            Paint(pixels, left, top, kEyeWidth, height, true);
            if (height >= kPupilMinEyeHeight)
                Paint(pixels, left + PupilX(x), top + PupilY(height, y),
                      kPupilWidth, kPupilHeight, false);
        }
    }
    // Independent golden rectangle coordinates in panel space, not a second
    // invocation of the geometry helpers. Compare every pixel, including status.
    const int top = 40 - height / 2;
    const int space = std::max(0, height - 4);
    const int pupil_top = top + std::clamp(space / 2 + y, 0, 2 * (space / 2));
    for (int row = 0; row < 64; ++row) {
        for (int col = 0; col < 128; ++col) {
            bool expected = false;
            for (int left : {51, 66}) {
                if (col >= left && col < left + 11 && row >= top && row < top + height) {
                    const int pupil_left = left + 4 + x;
                    expected = !(height >= 6 && col >= pupil_left && col < pupil_left + 3 &&
                                 row >= pupil_top && row < pupil_top + 4);
                }
            }
            assert(pixels.at(static_cast<size_t>(row) * 128 + col) == expected);
        }
    }
}

static void CheckTransition(Expression from, Expression to, uint32_t start, bool gaze) {
    FaceMoodMorph morph;
    const auto initial = morph.Step(start, from.name, true, gaze);
    assert(initial == (gaze ? from.aperture : 0));
    int previous = from.aperture;
    for (uint32_t age : {0U, 100U, 200U, 299U, 300U, 301U}) {
        const int height = morph.Step(start + 1 + age, to.name, true, gaze);
        const bool moving = from.aperture && to.aperture && from.aperture != to.aperture;
        if (!moving || age >= 300) {
            assert(height == (gaze ? to.aperture : 0));
        } else {
            assert(height >= std::min(from.aperture, to.aperture));
            assert(height <= std::max(from.aperture, to.aperture));
            if (age == 0) assert(height == from.aperture);
            assert(from.aperture < to.aperture ? height >= previous : height <= previous);
        }
        previous = height;
        const int visible_height = gaze && !height ? 14 : height;
        for (int x : {-3, 0, 3})
            for (int y : {-3, 0, 3}) {
                CheckFrame(visible_height, x, y, false);
                if (gaze) CheckFrame(visible_height, x, y, true);
            }
    }
    assert(morph.Step(start + 303, to.name, false, gaze) == 0);
    CheckFrame(0, 0, 0, false);
    assert(morph.Step(start + 304, to.name, true, false) == 0);
}

int main() {
    for (uint32_t start : {0U, 0xffffff80U})
        for (const auto& from : expressions)
            for (const auto& to : expressions)
                for (bool gaze : {false, true}) CheckTransition(from, to, start, gaze);
}
""")
    pie_flags = [] if sys.platform == "darwin" else ["-fno-pie", "-no-pie"]
    env = dict(os.environ, UBSAN_OPTIONS="halt_on_error=1", ASAN_OPTIONS="halt_on_error=1")
    subprocess.run(
        [compiler, "-std=c++17", "-O1", "-Wall", "-Wextra", "-Werror",
         "-fsanitize=address,undefined", *pie_flags, "-I", str(OVERLAY),
         str(source), "-o", str(binary)],
        check=True, timeout=60, env=env,
    )
    subprocess.run([str(binary)], check=True, timeout=60, env=env)
