#include "reference_decimator.h"
#include "reference_timeline.h"
#include <array>
#include <cassert>
#include <cmath>
#include <cstdio>

using desk_robot::ReferenceDecimator;

// Clearing history for silence must preserve the next emission phase even
// after the circular history wraps; cancellation must instead restart it.
static void CheckGapAndResetPhase() {
  for (int prefix : {63, 64, 65, 127, 128, 129, 31999, 32000, 32001}) {
    ReferenceDecimator d;
    int16_t y = 0;
    for (int i = 0; i < prefix; ++i) {
      assert(d.Push(i % 3 == 0 ? -32768 : 32767, y) == (i % 2 == 0));
    }
    d.ClearHistory();
    for (int i = 0; i < 130; ++i) {
      y = 12345;
      const bool emitted = d.Push(0, y);
      assert(emitted == ((prefix + i) % 2 == 0));
      assert(y == (emitted ? 0 : 12345));
    }
    d.Reset();
    assert(d.Push(0, y) && y == 0);
    y = 12345;
    assert(!d.Push(0, y) && y == 12345);
  }
}

// Use irregular accepted chunk sizes, including odd partial I2S writes.
// The ring clock and FIR must agree on the cumulative 2:1 frame count.
static void CheckAcceptedChunkPhase() {
  ReferenceDecimator d;
  desk_robot::PlaybackReferenceClock clock;
  constexpr int64_t origin = 1000000;
  constexpr std::array<int, 9> sizes{1, 3, 63, 64, 65, 1919, 1920, 1921, 32000};
  uint64_t accepted = 0, published = 0;
  assert(clock.silence_frames(origin, 16384) == 0);
  for (int round = 0; round < 20; ++round) {
    for (const int size : sizes) {
      assert(clock.silence_frames(origin, 16384) == 0);
      for (int i = 0; i < size; ++i) {
        const uint32_t bits = static_cast<uint32_t>(accepted) * 2654435761U;
        const auto pcm = static_cast<int32_t>(int64_t(bits) + INT32_MIN);
        int16_t y = 12345;
        const bool emitted = d.Push(desk_robot::Pcm32ToReferenceSample(pcm), y);
        assert(emitted == (accepted % 2 == 0));
        if (emitted) ++published;
        else assert(y == 12345);
        ++accepted;
      }
      clock.accepted_output_frames(size);
      assert(published == (accepted + 1) / 2);
      assert(clock.represented_end_us() ==
             origin + static_cast<int64_t>(accepted * 1000000U / 32000U));
      assert(clock.future_reference_frames(origin, UINT64_MAX) == published);
    }
  }
}

int main() {
  CheckAcceptedChunkPhase();
  CheckGapAndResetPhase();
  using desk_robot::Pcm32ToReferenceSample;
  assert(Pcm32ToReferenceSample(INT32_MAX) == 32767);
  assert(Pcm32ToReferenceSample(INT32_MIN) == -32768);
  assert(Pcm32ToReferenceSample(INT32_MAX - 32767) == 32767);
  assert(Pcm32ToReferenceSample(32767) == 0);
  assert(Pcm32ToReferenceSample(32768) == 1);
  assert(Pcm32ToReferenceSample(-32767) == 0);
  assert(Pcm32ToReferenceSample(-32768) == -1);
  assert(Pcm32ToReferenceSample(INT32_MIN + 32768) == -32768);
  assert(Pcm32ToReferenceSample(INT32_MIN + 32769) == -32767);
  assert(Pcm32ToReferenceSample(INT32_MAX - 32768) == 32767);
  // Sweep the three values around every representable half-step. This
  // checks signed tie handling and the transition into positive saturation.
  for (int64_t lower = -32768; lower < 32767; ++lower) {
    const int32_t half = static_cast<int32_t>(lower * 65536 + 32768);
    assert(Pcm32ToReferenceSample(half - 1) == lower);
    assert(Pcm32ToReferenceSample(half) == (lower < 0 ? lower : lower + 1));
    assert(Pcm32ToReferenceSample(half + 1) == lower + 1);
  }
  for (int32_t sample = -32768; sample <= 32767; ++sample)
    assert(Pcm32ToReferenceSample(sample * 65536) == sample);
  constexpr double pi = 3.14159265358979323846;
  auto gain = [&](double f, double phase) {
    ReferenceDecimator d;
    double out = 0;
    int16_t y = 0;
    int count = 0;
    for (int i = 0; i < 32000; ++i) {
      const auto x = static_cast<int16_t>(
          std::lround(12000 * std::cos(2 * pi * f * i / 32000 + phase)));
      if (d.Push(x, y) && i >= 320) {
        out += double(y) * y;
        ++count;
      }
    }
    return std::sqrt(out / count) / (12000 / std::sqrt(2.0));
  };
  for (int f = 100; f <= 6000; f += 100)
    assert(std::abs(gain(f, 0) - 1) < 0.01);
  // At exactly 8 kHz, sampling phase can mask a poor filter.
  for (int f = 8000; f <= 16000; f += 100) {
    assert(gain(f, 0) < 0.002);
    assert(gain(f, pi / 2) < 0.002);
  }
  // Off-grid frequencies and nonsymmetric phases exercise aliases that a
  // regular 100 Hz sweep can miss. Keep the existing attenuation contract.
  double worst_alias = 0.0;
  for (int f = 9007; f <= 15000; f += 137) {
    for (double phase : {0.37, 1.11, 2.41}) {
      const double alias = gain(f, phase);
      worst_alias = std::max(worst_alias, alias);
      assert(alias < 0.002);
    }
  }
  std::printf("Worst off-grid alias: %.6f (%.2f dB)\n",
              worst_alias, 20.0 * std::log10(worst_alias));
  ReferenceDecimator d;
  int16_t y = 0;
  // Golden impulse response at -32768: Q15 coefficients are directly
  // observable without rounding ambiguity. Both phases cover all 63 taps,
  // including sidelobes, and verify zero before and after the response.
  constexpr std::array<int16_t, 32> half_response{
      -1,-15,-21,1,34,19,-43,-57,34,106,9,-151,-96,163,221,-111,
      -362,-35,475,291,-497,-649,350,1078,64,-1519,-908,1906,2698,
      -2170,-10158,-14080};
  // A matched-sign full-scale window exceeds both PCM16 rails before
  // clipping. Unlike a DC test, it detects removal of the FIR clamp.
  for (int polarity : {-1, 1}) {
    d.Reset();
    for (int i = 0; i < 63; ++i) {
      const int tap = half_response[std::min(i, 62 - i)];
      const int16_t input = (tap * polarity < 0) ? 32767 : -32768;
      const bool emitted = d.Push(input, y);
      if (i == 62) {
        assert(emitted);
        assert(y == (polarity > 0 ? 32767 : -32768));
      }
    }
  }
  for (int impulse : {128, 129}) {
    d.Reset();
    for (int i = 0; i < 256; ++i) {
      const bool emitted = d.Push(i == impulse ? -32768 : 0, y);
      assert(emitted == (i % 2 == 0));
      if (!emitted) continue;
      const int delay = i - impulse;
      const int16_t expected = delay < 0 || delay > 62 ? 0 :
          half_response[std::min(delay, 62 - delay)];
      assert(y == expected);
    }
  }
  d.Reset();
  for (int i = 0; i < 200; ++i)
    if (d.Push(32767, y) && i >= 64) assert(y == 32767);
  d.Reset();
  for (int i = 0; i < 200; ++i)
    if (d.Push(-32768, y) && i >= 64) assert(y == -32768);
  d.Reset();
  assert(d.Push(30000, y));
  d.ClearHistory();
  assert(!d.Push(0, y));
  assert(d.Push(0, y) && y == 0);
  d.Reset();
  assert(d.Push(0, y) && y == 0);
  for (int i = 0; i < 32000; ++i)
    d.Push(i % 2 ? 32767 : -32768, y);
}
