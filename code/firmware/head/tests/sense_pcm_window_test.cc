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
  // Accepted I2S frames are not proof of a usable acoustic stimulus.
  // A full, correctly timestamped capture of digital silence must fail.
  SensePcmWindow silent_reference;
  std::array<std::int16_t, 320> quiet{};
  assert(silent_reference.begin(data.data(), 1000000));
  for (int i = 1; i <= 200; ++i)
    silent_reference.offer(mic.data(), quiet.data(), 320,
                           1000000 + i * 20000, true);
  assert(silent_reference.frames_received() == SensePcmWindow::kFrames);
  assert(silent_reference.failed() && !silent_reference.ready());
  assert(silent_reference.take().interleaved == nullptr);
  assert(silent_reference.discard() == data.data());
  assert(!silent_reference.occupied());
  // A full mic frame count may likewise be all zero after a PDM fault.
  // Calibration requires actual nonzero evidence in BOTH source channels.
  SensePcmWindow silent_microphone;
  assert(silent_microphone.begin(data.data(), 1000000));
  for (int i = 1; i <= 200; ++i)
    silent_microphone.offer(quiet.data(), ref.data(), 320,
                            1000000 + i * 20000, true);
  assert(silent_microphone.frames_received() == SensePcmWindow::kFrames);
  assert(silent_microphone.failed() && !silent_microphone.ready());
  assert(silent_microphone.take().interleaved == nullptr);
  assert(silent_microphone.discard() == data.data());
  assert(!silent_microphone.occupied());
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
  // A blocking microphone callback could start before the operator
  // enabled private capture, then return after START. Its preceding PCM
  // must never be saved in the authenticated recording.
  SensePcmWindow consent_edge;
  assert(consent_edge.begin(data.data(), 1000000));
  consent_edge.offer(mic.data(), ref.data(), 320, 1001000, true);
  assert(consent_edge.frames_received() == 0);
  assert(!consent_edge.failed() && !consent_edge.ready());
  for (int i = 1; i <= 200; ++i)
    consent_edge.offer(mic.data(), ref.data(), 320,
                       1001000 + i * 20000, true);
  assert(consent_edge.ready());
  auto after_consent = consent_edge.take();
  assert(after_consent.frames == 64000);
  assert(after_consent.first_sample_us == 1001000);
  assert(after_consent.last_sample_us == 5001000);
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
  // A 180 ms stall between 20 ms microphone callbacks is not continuous
  // source timing, although the older 250 ms permissive gap accepted it.
  SensePcmWindow missing;
  assert(missing.begin(data.data(), 1000000));
  missing.offer(mic.data(), ref.data(), 320, 1020000, true);
  missing.offer(mic.data(), ref.data(), 320, 1200000, true);
  assert(missing.failed());
  assert(!missing.ready());
  assert(missing.discard() == data.data());
  // Small irregular gaps can accumulate and invalidate a full 64,000-frame
  // window without exceeding the callback-level jitter threshold.
  SensePcmWindow drifted;
  assert(drifted.begin(data.data(), 1000000));
  for (int i = 1; i <= 200; ++i)
    drifted.offer(mic.data(), ref.data(), 320,
                  1000000 + i * 20500, true);
  assert(drifted.frames_received() == SensePcmWindow::kFrames);
  assert(drifted.failed() && !drifted.ready());
  assert(drifted.take().interleaved == nullptr);
  assert(drifted.discard() == data.data());
  // Monotonic callback END timestamps alone cannot show that the inferred
  // 20 ms source intervals do not overlap. Repeated source samples would
  // corrupt A2 acoustic lag/drift calibration even when 64k frames arrive.
  SensePcmWindow overlap;
  assert(overlap.begin(data.data(), 1000000));
  overlap.offer(mic.data(), ref.data(), 320, 1020000, true);
  overlap.offer(mic.data(), ref.data(), 320, 1030000, true);
  assert(overlap.failed() && !overlap.ready());
  assert(overlap.frames_received() == 320);
  assert(overlap.discard() == data.data());
  // A 3 ms overlap still exceeds the bounded scheduler jitter allowance.
  assert(overlap.begin(data.data(), 1000000));
  overlap.offer(mic.data(), ref.data(), 320, 1020000, true);
  overlap.offer(mic.data(), ref.data(), 320, 1037000, true);
  assert(overlap.failed() && overlap.frames_received() == 320);
  assert(overlap.discard() == data.data());
  // A small 1 ms callback scheduling variation remains permissible.
  SensePcmWindow jitter;
  assert(jitter.begin(data.data(), 1000000));
  for (int i = 1; i <= 200; ++i) {
    jitter.offer(mic.data(), ref.data(), 320,
                 1000000 + i * 20000 - (i > 1 ? 1000 : 0), true);
  }
  assert(jitter.ready() && !jitter.failed());
  assert(jitter.take().frames == SensePcmWindow::kFrames);
  return 0;
}
