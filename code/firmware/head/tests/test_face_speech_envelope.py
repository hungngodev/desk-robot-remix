"""Exercise the Sense digital speech envelope and cosmetic mouth policy."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SENSE = Path(__file__).resolve().parents[1] / "sense"


@pytest.mark.parametrize("standard", ["c++11", "c++17"])
def test_speech_envelope_noise_peak_slew_and_reset(tmp_path, standard):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("Native C++ compiler unavailable")
    source = tmp_path / "speech.cc"
    binary = tmp_path / "speech"
    source.write_text(r'''
#include "face_speech_envelope.hpp"
#include <cassert>
#include <limits>
using namespace desk_robot;
int main() {
    SpeechLevelWindow level;
    FaceMouthAnimator mouth;
    assert(!level.Read(0).fresh);
    assert(mouth.Step(level.Read(0), false) == 0);
    for (int noise = 0; noise <= 256; ++noise) {
        level.Publish(noise * 100U, 100, noise);
        assert(mouth.Step(level.Read(noise), true) == 1);
    }
    level.Publish(1400U * 100U, 100, 270);
    assert(mouth.Step(level.Read(270), true) == 1);
    level.Publish(1600U * 100U, 100, 280);
    assert(mouth.Step(level.Read(280), true) == 2);
    level.Publish(0, 100, 290);
    assert(mouth.Step(level.Read(290), true) == 1);
    // An isolated full-scale sample among 100 quiet samples is not a full mouth.
    level.Publish(32768, 100, 300);
    assert(mouth.Step(level.Read(300), true) == 1);
    level.Publish(32768U * 100U, 100, 400);
    assert(level.Read(400).mean_abs == 32768);
    assert(mouth.Step(level.Read(400), true) == 3);
    assert(mouth.Step(level.Read(100400), true) == 5);
    assert(mouth.Step(level.Read(200400), true) == 7);
    assert(!level.Read(200401).fresh);
    assert(mouth.Step(level.Read(200401), true) == 1);
    assert(!level.Read(399).fresh);
    level.Publish(8192U * 100U, 100, 300000);
    for (int i = 0; i < 3; ++i) mouth.Step(level.Read(300000), true);
    level.Publish(0, 100, 400000);
    assert(mouth.Step(level.Read(400000), true) == 5);
    assert(mouth.Step(level.Read(500000), true) == 3);
    assert(mouth.Step(level.Read(600000), true) == 1);
    level.Publish(8192U * 100U, 100, 700000);
    assert(mouth.Step(level.Read(700000), true) == 3);
    assert(mouth.Step(level.Read(700001), false) == 0);
    level.Reset();
    assert(!level.Read(700002).fresh);
    assert(mouth.Step(level.Read(700002), true) == 1);
    level.Publish(8192, 0, 800000);
    assert(!level.Read(800000).fresh);
    assert(!level.Read(-1).fresh);
    assert(level.Read(800000).mean_abs == 0);
    // Extreme timestamps must never overflow the age calculation.
    const auto max_time = std::numeric_limits<int64_t>::max();
    level.Publish(1, 1, 0);
    assert(!level.Read(max_time).fresh);
    level.Publish(std::numeric_limits<uint64_t>::max(), 1, max_time - 200000);
    assert(level.Read(max_time).fresh);
    assert(level.Read(max_time).mean_abs == 32768);
    assert(!level.Read(std::numeric_limits<int64_t>::min()).fresh);
    level.Publish(0, -1, max_time);
    level.Publish(0, 1, -1);
    assert(level.Read(max_time).mean_abs == 32768);
    assert(mouth.Step(level.Read(max_time), true) == 3);
    assert(mouth.Step(level.Read(max_time), true) == 5);
    assert(mouth.Step(level.Read(max_time), true) == 7);
    assert(mouth.Step(level.Read(max_time), false) == 0);
    assert(mouth.Step({std::numeric_limits<uint16_t>::max(), true}, true) == 3);
    assert(mouth.Step({}, true) == 1);
    level.Reset();
    assert(!level.Read(max_time).fresh);
    assert(level.Read(max_time).mean_abs == 0);
}
''')
    flags = [] if sys.platform == "darwin" else ["-fno-pie", "-no-pie"]
    env = dict(os.environ, ASAN_OPTIONS="halt_on_error=1", UBSAN_OPTIONS="halt_on_error=1")
    subprocess.run(
        [compiler, f"-std={standard}", "-Wall", "-Wextra", "-Werror",
         "-fsanitize=address,undefined", *flags, "-I", str(SENSE), str(source),
         "-o", str(binary)], check=True, timeout=60, env=env,
    )
    subprocess.run([str(binary)], check=True, timeout=30, env=env)
