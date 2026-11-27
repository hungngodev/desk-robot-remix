"""Host regression for PCM acceptance through the real cosmetic envelope."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SENSE = Path(__file__).resolve().parents[1] / "sense"


def test_accepted_pcm_extrema_and_burst_envelope(tmp_path):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("Native C++ compiler unavailable")
    codec = (SENSE / "sense_reference_codec.cc").read_text()
    publisher = "void SenseReferenceCodec::PublishAcceptedLocked(" + codec.split(
        "void SenseReferenceCodec::PublishAcceptedLocked(", 1
    )[1].split("bool SenseReferenceCodec::ReadReferenceLocked(", 1)[0]
    source = tmp_path / "speech_pcm.cc"
    binary = tmp_path / "speech_pcm"
    source.write_text(r'''
#include "face_speech_envelope.hpp"
#include "reference_decimator.h"
#include <array>
#include <cassert>
#include <limits>
#include <vector>
using namespace desk_robot;

// Isolate digital acceptance; neither I2S nor acoustic timing is simulated.
struct SenseReferenceCodec {
    SpeechLevelWindow speech_level_;
    ReferenceDecimator reference_decimator_;
    struct Clock {
        std::vector<int> chunks;
        void accepted_output_frames(int samples) { chunks.push_back(samples); }
    } reference_clock_;
    std::vector<int64_t> silence_times;
    std::vector<int16_t> reference_samples;
    void FillSilenceLocked(int64_t now) { silence_times.push_back(now); }
    void PushLocked(int16_t sample) { reference_samples.push_back(sample); }
    void PublishAcceptedLocked(const int32_t*, int, int64_t);
};
''' + publisher + r'''
int main() {
    constexpr auto lo = std::numeric_limits<int32_t>::min();
    constexpr auto hi = std::numeric_limits<int32_t>::max();
    // Observe the actual publisher's reference output and clock calls, not
    // only its cosmetic envelope. The unaccepted suffix contains loud PCM.
    SenseReferenceCodec partial;
    const std::array<int32_t, 3> impulse{{lo, hi, hi}};
    const std::array<int32_t, 2> silence{{0, 0}};
    partial.PublishAcceptedLocked(impulse.data(), 1, 10);
    assert((partial.reference_samples == std::vector<int16_t>{-1}));
    partial.PublishAcceptedLocked(silence.data(), 1, 41);
    assert((partial.reference_samples == std::vector<int16_t>{-1}));
    partial.PublishAcceptedLocked(silence.data() + 1, 1, 72);
    assert((partial.reference_samples == std::vector<int16_t>{-1, -21}));
    assert((partial.reference_clock_.chunks == std::vector<int>{1, 1, 1}));
    assert((partial.silence_times == std::vector<int64_t>{10, 41, 72}));
    assert(partial.speech_level_.Read(72).fresh);
    assert(partial.speech_level_.Read(72).mean_abs == 0);
    SenseReferenceCodec codec;
    FaceMouthAnimator mouth;
    auto& level = codec.speech_level_;
    std::array<int32_t, 100> pcm{};
    auto publish = [&](int64_t now) {
        codec.PublishAcceptedLocked(pcm.data(), pcm.size(), now);
        assert(level.Read(now).fresh);
        return level.Read(now).mean_abs;
    };
    assert(publish(0) == 0);
    assert(mouth.Step(level.Read(0), true) == 1);
    pcm.fill(lo);
    assert(publish(100000) == 32768);
    pcm.fill(hi);
    assert(publish(110000) == 32767);
    // An incorrectly narrowed abs(-32768) can be masked by saturation
    // on an all-negative chunk, but cannot pass this sparse-peak check.
    pcm.fill(0);
    pcm[0] = lo;
    assert(publish(120000) == 327);
    pcm[1] = hi;
    assert(publish(130000) == 655);
    // No unaccepted suffix may contribute to the level.
    codec.PublishAcceptedLocked(pcm.data(), 1, 140000);
    assert(level.Read(140000).mean_abs == 32768);
    pcm.fill(0);
    for (int i = 0; i < 20; ++i) {
        const int64_t now = 200000 + i * 100000;
        pcm.fill(i % 2 == 0 ? lo : 0);
        publish(now);
        assert(mouth.Step(level.Read(now), true) == (i % 2 == 0 ? 3 : 1));
    }
    // Sustained burst and fresh digital silence: two pixels per OLED tick.
    pcm.fill(lo);
    for (int i = 0; i < 3; ++i) {
        const int64_t now = 2200000 + i * 100000;
        publish(now);
        assert(mouth.Step(level.Read(now), true) == 3 + 2 * i);
    }
    pcm.fill(0);
    for (int i = 0; i < 3; ++i) {
        const int64_t now = 2500000 + i * 100000;
        publish(now);
        assert(mouth.Step(level.Read(now), true) == 5 - 2 * i);
    }
    pcm.fill(hi);
    publish(2800000);
    assert(mouth.Step(level.Read(2800000), true) == 3);
    assert(mouth.Step(level.Read(2900000), true) == 5);
    assert(mouth.Step(level.Read(3000000), true) == 7);
    assert(mouth.Step(level.Read(3000001), true) == 1); // stale bypass
    publish(3100000);
    assert(mouth.Step(level.Read(3100000), true) == 3);
    assert(mouth.Step(level.Read(3100000), false) == 0); // priority bypass
    level.Reset();
    assert(!level.Read(3100001).fresh);
    assert(mouth.Step(level.Read(3100001), true) == 1);
}
''')
    flags = [] if sys.platform == "darwin" else ["-fno-pie", "-no-pie"]
    env = dict(os.environ, ASAN_OPTIONS="halt_on_error=1", UBSAN_OPTIONS="halt_on_error=1")
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
         "-fsanitize=address,undefined", *flags, "-I", str(SENSE), str(source),
         "-o", str(binary)], check=True, timeout=60, env=env,
    )
    subprocess.run([str(binary)], check=True, timeout=30, env=env)
