#include "reference_decimator.h"
#include <array>
#include <cassert>
#include <cmath>
#include <cstdio>

using desk_robot::ReferenceDecimator;

int main() {
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
