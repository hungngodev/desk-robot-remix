"""Exercise the real cosmetic mood bridge, including priority preemption."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HEAD = Path(__file__).resolve().parents[1]


def test_face_mood_morph_native(tmp_path):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("Native C++ compiler unavailable")
    source = tmp_path / "morph.cc"
    binary = tmp_path / "morph"
    source.write_text(r"""
#include "face_mood_morph.hpp"
#include <cassert>
#include <initializer_list>
using desk_robot::FaceMoodMorph;
int main() {
    for (uint32_t start : {0U, 0xffffff00U}) {
        FaceMoodMorph face;
        assert(face.Step(start, "happy", true) == 0);
        assert(face.Step(start + 100, "surprised", true) == 8);
        const auto intermediate = face.Step(start + 200, "surprised", true);
        assert(intermediate > 8 && intermediate < 14);
        const auto before = face.Step(start + 250, "surprised", true);
        assert(before == 11);
        assert(face.Step(start + 250, "sleepy", true) == before);
        const auto closing = face.Step(start + 350, "sleepy", true);
        assert(closing < before && closing > 2);
        assert(face.Step(start + 450, "sleepy", true) < closing);
        assert(face.Step(start + 550, "sleepy", true) == 0);
        assert(face.Step(start + 650, "sleepy", true) == 0);
        assert(face.Step(start + 700, "happy", true) == 2);
        // Fault/privacy/voice owner must cancel without waiting for easing.
        assert(face.Step(start + 701, "happy", false) == 0);
        assert(face.Step(start + 702, "happy", true) == 0);
        assert(face.Step(start + 703, "surprised", true) == 8);
        assert(face.Step(start + 704, "unsupported", true) == 0);
        assert(face.Step(start + 705, "sleepy", true) == 0);
    }
}
""")
    pie = [] if sys.platform == "darwin" else ["-fno-pie", "-no-pie"]
    env = dict(os.environ, UBSAN_OPTIONS="halt_on_error=1", ASAN_OPTIONS="halt_on_error=1")
    subprocess.run(
        [
            compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
            "-fsanitize=address,undefined", *pie, "-I", str(HEAD / "overlay"),
            str(source), "-o", str(binary),
        ],
        check=True, timeout=60, env=env,
    )
    subprocess.run([str(binary)], check=True, timeout=30, env=env)
