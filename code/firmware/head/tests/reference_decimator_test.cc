#include "reference_decimator.h"
#include <cassert>
#include <cmath>

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
  ReferenceDecimator d;
  int16_t y = 0;
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
