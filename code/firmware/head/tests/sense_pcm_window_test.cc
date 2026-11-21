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
  // A final PDM read can overrun a four-second window. The last
  // timestamp must describe the last RECORDED sample, not the later
  // unrecorded samples in the tail of that same hardware read.
  SensePcmWindow partial;
  assert(partial.begin(data.data(), 1000000));
  for (int i = 1; i <= 199; ++i)
    partial.offer(mic.data(), ref.data(), 320, 1000000 + i * 20000, true);
  partial.offer(mic.data(), ref.data(), 220, 4993750, true);
  assert(partial.frames_received() == 63900 && !partial.ready());
  partial.offer(mic.data(), ref.data(), 320, 5013750, true);
  assert(partial.ready());
  const auto clipped = partial.take();
  assert(clipped.frames == 64000);
  assert(clipped.first_sample_us == 1000000);
  assert(clipped.last_sample_us == 5000000);
  assert(clipped.last_sample_us - clipped.first_sample_us == 4000000);
  assert(clipped.interleaved[127999] == -5678);
  assert(!partial.occupied());
  return 0;
}
