"""Keep the existing OLED theme geometry inside its allocated emotion slot."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

OVERLAY = Path(__file__).resolve().parents[1] / "overlay"


def test_face_eye_geometry(tmp_path):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("Native C++ compiler unavailable")
    source = tmp_path / "geometry.cc"
    binary = tmp_path / "geometry"
    source.write_text(r"""
#include "face_eye_geometry.hpp"
#include <cassert>
#include <initializer_list>
#include <limits>
using namespace desk_robot::face_eye_geometry;
int main() {
    static_assert(kPanelWidth == 128 && kPanelHeight == 64);
    static_assert(kStatusHeight == 16 && kSlotWidth == 32 && kSlotHeight == 48);
    static_assert(kEyeCount == 2 && kEyeWidth == 11);
    static_assert(kOpenHeight == 14 && kClosedHeight == 2);
    static_assert(kGazeExtent == 3 && kNodReturn == -2);
    static_assert(EyeX(0) == 3 && EyeX(1) == 18 && EyeY(14) == 17);
    static_assert(PupilX(0) == 4 && PupilY(14, 0) == 5);
    constexpr auto inf = std::numeric_limits<float>::infinity();
    const auto nan = std::numeric_limits<float>::quiet_NaN();
    assert(NormalizedGazeOffset(nan) == 0);
    assert(NormalizedGazeOffset(inf) == 0);
    assert(NormalizedGazeOffset(-inf) == 0);
    assert(NormalizedGazeOffset(-5.0f) == -3);
    assert(NormalizedGazeOffset(5.0f) == 3);
    assert(NormalizedGazeOffset(-1.0f) == -3);
    assert(NormalizedGazeOffset(1.0f) == 3);
    assert(NormalizedGazeOffset(-0.5f) == -2);
    assert(NormalizedGazeOffset(0.5f) == 2);
    assert(NormalizedGazeOffset(0.0f) == 0);
    for (float x : {nan, -inf, inf, -5.0f, -1.0f, -0.5f, 0.0f, 0.5f, 1.0f, 5.0f}) {
        for (float y : {nan, -inf, inf, -5.0f, -1.0f, -0.5f, 0.0f, 0.5f, 1.0f, 5.0f}) {
            const int px = PupilX(NormalizedGazeOffset(x));
            const int py = PupilY(kOpenHeight, NormalizedGazeOffset(y));
            assert(px >= 0 && px + kPupilWidth <= kEyeWidth);
            assert(py >= 0 && py + kPupilHeight <= kOpenHeight);
        }
    }
    for (int d : {std::numeric_limits<int>::min(), -128, 127,
                  std::numeric_limits<int>::max()}) {
        assert(PupilX(d) == PupilX(d < 0 ? -3 : 3));
        assert(PupilY(kOpenHeight, d) == PupilY(kOpenHeight, d < 0 ? -3 : 3));
        assert(PupilY(std::numeric_limits<int>::min(), d) == 0);
        assert(PupilY(std::numeric_limits<int>::max(), d) == PupilY(kOpenHeight, d));
    }
    // Check absolute screen coordinates, including the centered slot and status bar.
    constexpr int slot_x = (kPanelWidth - kSlotWidth) / 2;
    for (int i : {std::numeric_limits<int>::min(), -1, 0, 1, 2,
                  std::numeric_limits<int>::max()}) {
        assert(EyeX(i) == kEyeLeft + std::clamp(i, 0, kEyeCount - 1) * kEyeStride);
        const int left = slot_x + EyeX(i);
        assert(left >= slot_x && left + kEyeWidth <= slot_x + kSlotWidth);
        assert(left >= 0 && left + kEyeWidth <= kPanelWidth);
        for (int raw : {std::numeric_limits<int>::min(), -1, 0, 2, 6, 14, 255,
                        std::numeric_limits<int>::max()}) {
            const int height = std::clamp(raw, kClosedHeight, kOpenHeight);
            assert(EyeY(raw) == kSlotHeight / 2 - height / 2);
            const int top = kStatusHeight + EyeY(raw);
            assert(top >= kStatusHeight && top + height <= kPanelHeight);
            // The real renderer hides pupils in narrow/closed eyes.
            if (height < kPupilMinEyeHeight) continue;
            constexpr float biggest = std::numeric_limits<float>::max();
            for (float x : {nan, inf, -inf, -biggest, -1.0f, 0.0f, 1.0f, biggest}) {
                for (float y : {nan, inf, -inf, -biggest, -1.0f, 0.0f, 1.0f, biggest}) {
                    const int px = left + PupilX(NormalizedGazeOffset(x));
                    const int py = top + PupilY(raw, NormalizedGazeOffset(y));
                    assert(px >= left && px + kPupilWidth <= left + kEyeWidth);
                    assert(py >= top && py + kPupilHeight <= top + height);
                    assert(px >= 0 && px + kPupilWidth <= kPanelWidth);
                    assert(py >= kStatusHeight && py + kPupilHeight <= kPanelHeight);
                }
            }
        }
    }
    assert(NormalizedGazeOffset(std::numeric_limits<float>::max()) == kGazeExtent);
    assert(NormalizedGazeOffset(-std::numeric_limits<float>::max()) == -kGazeExtent);
    for (int h = kClosedHeight; h <= kOpenHeight; ++h) {
        assert(EyeY(h) >= 0 && EyeY(h) + h <= kSlotHeight);
        for (int i = 0; i < kEyeCount; ++i) {
            assert(EyeX(i) >= 0 && EyeX(i) + kEyeWidth <= kSlotWidth);
        }
        if (h < kPupilMinEyeHeight) continue;
        for (int d = -kGazeExtent; d <= kGazeExtent; ++d) {
            assert(PupilX(d) >= 0 && PupilX(d) + kPupilWidth <= kEyeWidth);
            assert(PupilY(h, d) >= 0 && PupilY(h, d) + kPupilHeight <= h);
            if (d < 0) assert(PupilY(h, d) < PupilY(h, 0));
            if (d > 0) assert(PupilY(h, d) > PupilY(h, 0));
            assert(PupilY(h, d) + PupilY(h, -d) == 2 * PupilY(h, 0));
        }
    }
}
""")
    pie_flags = [] if sys.platform == "darwin" else ["-fno-pie", "-no-pie"]
    subprocess.run(
        [
            compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
            "-fsanitize=address,undefined", "-fno-sanitize-recover=all", *pie_flags,
            "-I", str(OVERLAY), str(source), "-o", str(binary),
        ],
        check=True, timeout=60,
    )
    subprocess.run([str(binary)], check=True, timeout=30)
