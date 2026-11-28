"""Host stress of the production AEC ring operations, not the private PCM window."""

import re
import shutil
import subprocess
from pathlib import Path

from test_overlay import native_cpp_env, native_cpp_sanitizer_flags

HEAD = Path(__file__).resolve().parents[1]


def test_reference_ring_prime_chunks_across_10000_wraps(tmp_path):
    codec = (HEAD / "sense/sense_reference_codec.cc").read_text()
    header = (HEAD / "sense/sense_reference_codec.h").read_text()
    ring = int(re.search(r"kRingSize\s*=\s*(\d+);", header)[1])
    push = "void SenseReferenceCodec::PushLocked(" + codec.split(
        "void SenseReferenceCodec::PushLocked(", 1
    )[1].split("void SenseReferenceCodec::FillSilenceLocked(", 1)[0]
    read = "bool SenseReferenceCodec::ReadReferenceLocked(" + codec.split(
        "bool SenseReferenceCodec::ReadReferenceLocked(", 1
    )[1].split("int SenseReferenceCodec::Read(", 1)[0]
    harness = r"""
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>
struct SenseReferenceCodec {
    static constexpr uint64_t kRingSize = RING_SIZE, kDelaySamples = 0;
    struct Clock {
        uint64_t future = 0;
        uint64_t future_reference_frames(int64_t, uint64_t cap) const {
            return std::min(future, cap);
        }
    } reference_clock_;
    uint64_t write_index_ = 0, last_reference_read_write_index_ = 0;
    uint32_t missing_reference_reads_ = 0, consecutive_missing_reference_reads_ = 0;
    uint32_t reference_overwrite_reads_ = 0;
    bool reference_integrity_failed_ = false, reference_read_seen_ = false;
    std::array<int16_t, kRingSize> reference_{};
    void PushLocked(int16_t sample);
    bool ReadReferenceLocked(int16_t* dest, int frames, int64_t now_us);
};
""" + push + read + r"""
// Deliberately not periodic at a power of two: stale slots cannot masquerade
// as their replacements after a wrap. The oracle never uses ring indices.
static int16_t sample(uint64_t n) {
    return static_cast<int16_t>(static_cast<int64_t>(n * 7919 % 65521) - 32760);
}
int main() {
    constexpr uint64_t ring = SenseReferenceCodec::kRingSize;
    constexpr std::array<int, 7> primes{3, 17, 257, 509, 1021, 1531, 2039};
    constexpr int16_t guard = -32768;
    SenseReferenceCodec codec;
    std::array<int16_t, 2041> out{};
    uint64_t written = 0, iteration = 0, crossing = 0;
    // Actual codec serializes these operations with reference_mutex_.
    // Alternate producer and consumer in varied order, not a data race.
    while (written < ring * 10000) {
        const auto chunk = primes[iteration % primes.size()];
        for (int i = 0; i < chunk; ++i) codec.PushLocked(sample(written++));
        assert(codec.write_index_ == written);
        const auto frames = primes[(iteration * 3 + 2) % primes.size()];
        const auto future = (iteration * 37) % 2048;
        codec.reference_clock_.future = future;
        out.fill(guard);
        const bool valid = written >= future + frames;
        assert(codec.ReadReferenceLocked(out.data() + 1, frames, 10000) == valid);
        if (valid) {
            const auto start = written - future - frames;
            if (start / ring != (start + frames - 1) / ring) ++crossing;
            for (int i = 0; i < frames; ++i)
                assert(out[i + 1] == sample(start + i));
        } else {
            for (int i = 0; i < frames; ++i) assert(out[i + 1] == 0);
        }
        assert(out.front() == guard);
        assert(std::all_of(out.begin() + frames + 1, out.end(),
                           [](auto value) { return value == guard; }));
        ++iteration;
    }
    assert(crossing > 1000);
    assert(codec.reference_overwrite_reads_ == 0);
    assert(!codec.reference_integrity_failed_);
    std::cout << written / ring << " wraps, " << crossing << " crossing reads\n";
}
"""
    source = tmp_path / "sense_ring_property.cc"
    source.write_text(harness.replace("RING_SIZE", str(ring)))
    compiler = shutil.which("g++") or shutil.which("c++")
    assert compiler is not None, "A native C++17 compiler is required"
    binary = tmp_path / "sense_ring_property"
    subprocess.run(
        [compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror",
         *native_cpp_sanitizer_flags(), str(source), "-o", str(binary)],
        check=True, env=native_cpp_env(),
    )
    subprocess.run([str(binary)], check=True, timeout=60)
