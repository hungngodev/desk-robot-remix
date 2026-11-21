#include "sense_pcm_window.h"
#include <array>
#include <cassert>
#include <cstdint>
using desk_robot::SensePcmWindow;
int main() {
  static std::array<std::int16_t, SensePcmWindow::kFrames * 2> data{};
  assert(SensePcmWindow::kBytes == 256000);
  SensePcmWindow capture;
  assert(!capture.ready());
  assert(capture.begin(data.data(), 1000000));
  assert(!capture.begin(data.data(), 1000001));
  std::array<std::int16_t, 320> mic{};
  std::array<std::int16_t, 320> ref{};
  mic.fill(1234); ref.fill(-5678);
  for (int i=1; i<=200; ++i) capture.offer(mic.data(), ref.data(), 320, 1000000 + i * 20000, true);
  assert(capture.ready());
  assert(capture.frames_received()==SensePcmWindow::kFrames);
  auto result=capture.take();
  assert(result.frames==64000 && result.interleaved == data.data());
  assert(result.first_sample_us == 1000000);
  assert(result.last_sample_us == 5000000);
  assert(result.interleaved[0]==1234 && result.interleaved[1]==-5678);
  assert(result.interleaved[127998]==1234 && result.interleaved[127999]==-5678);
  assert(!capture.ready() && !capture.occupied());
  assert(capture.begin(data.data(), 1000000));
  capture.offer(mic.data(), ref.data(), 320, 1020000, false);
  assert(capture.failed() && !capture.ready());
  assert(capture.take().interleaved == nullptr);
  assert(capture.discard() == data.data());
  assert(capture.begin(data.data(), 1000000));
  capture.offer(mic.data(), ref.data(), 320, 1700000, true);
  assert(capture.failed());
  assert(capture.discard() == data.data());
  assert(capture.begin(data.data(), 1000000));
  capture.offer(mic.data(), ref.data(), 320, 1020000, true);
  capture.offer(mic.data(), ref.data(), 320, 1020000, true);
  assert(capture.failed());
  assert(capture.discard() == data.data());
  return 0;
}
