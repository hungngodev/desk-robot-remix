#include "sense_pcm_window.h"
#include <array>
#include <cassert>
#include <cstdint>
#include <limits>
using desk_robot::SensePcmWindow;

// Exercise the real capture window with mixed callback sizes, simulated
// source clocks and Nyquist-frequency PCM. This is not an acoustic AEC test.
static void stress_capture_clock(std::uint32_t source_rate, int stall_us) {
  constexpr std::size_t guard = 8;
  constexpr std::int16_t sentinel = 12345;
  static std::array<std::int16_t, SensePcmWindow::kFrames * 2 + guard * 2> storage;
  std::array<std::int16_t, 2048> mic{}, ref{};
  storage.fill(sentinel);
  auto* data = storage.data() + guard;
  SensePcmWindow capture;
  constexpr std::int64_t start = 1000000;
  assert(capture.begin(data, start));
  std::uint32_t total = 0;
  const bool valid = source_rate == SensePcmWindow::kSampleRate && stall_us == 0;
  for (int i = 0; i < 200; ++i) {
    const std::uint32_t frames = 480 * (1 + (i * 7) % 4);
    for (std::uint32_t n = 0; n < frames; ++n) {
      mic[n] = ((total + n) % 2) ? INT16_MIN : INT16_MAX;
      ref[n] = ((total + n) % 4 < 2) ? -23456 : 23456;
    }
    total += frames;
    const auto jitter = i == 0 ? 0 : ((i % 3) - 1) * 1000;
    const auto end = start + std::int64_t{total} * 1000000 / source_rate
        + jitter + (i >= 5 ? stall_us : 0);
    const auto before = capture.frames_received();
    const bool terminal = capture.failed() || capture.ready();
    capture.offer(mic.data(), ref.data(), frames, end, true);
    assert(capture.frames_received() <= SensePcmWindow::kFrames);
    assert(capture.frames_received() >= before);
    if (terminal) assert(capture.frames_received() == before);
    for (std::size_t n = 0; n < guard; ++n) {
      assert(storage[n] == sentinel);
      assert(storage[storage.size() - 1 - n] == sentinel);
    }
  }
  if (valid) {
    assert(capture.ready() && !capture.failed());
    const auto result = capture.take();
    assert(result.interleaved == data && result.frames == SensePcmWindow::kFrames);
    assert(result.first_sample_us == start);
    assert(result.last_sample_us >= start + 3999000);
    assert(result.last_sample_us <= start + 4001000);
    for (std::uint32_t n = 0; n < result.frames; ++n) {
      assert(data[2 * n] == (n % 2 ? INT16_MIN : INT16_MAX));
      assert(data[2 * n + 1] == (n % 4 < 2 ? -23456 : 23456));
    }
  } else {
    assert(capture.failed() && !capture.ready());
    assert(capture.take().interleaved == nullptr);
    // Unaccepted space stays untouched even after repeated callbacks.
    for (std::uint32_t n = capture.frames_received() * 2;
         n < SensePcmWindow::kFrames * 2; ++n) {
      assert(data[n] == sentinel);
    }
    assert(capture.discard() == data);
  }
  assert(!capture.occupied());
}

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
  // A dropped PDM callback can fit both timing tolerances, so explicit
  // failure notification must invalidate the active window immediately.
  SensePcmWindow short_read;
  short_read.invalidate_read(1000000);
  assert(!short_read.failed());
  assert(short_read.begin(data.data(), 1000000));
  short_read.invalidate_read(999999);
  assert(!short_read.failed());
  short_read.offer(mic.data(), ref.data(), 320, 1020000, true);
  short_read.invalidate_read(1040000);
  for (int i = 2; i <= 200; ++i)
    short_read.offer(mic.data(), ref.data(), 320,
                     1000000 + (i + 1) * 20000, true);
  assert(short_read.failed() && !short_read.ready());
  assert(short_read.frames_received() == 320);
  assert(short_read.take().interleaved == nullptr);
  assert(short_read.discard() == data.data());
  assert(short_read.begin(data.data(), 6000000));
  short_read.invalidate_read(6000000);
  assert(short_read.failed());
  assert(short_read.discard() == data.data());
  assert(short_read.begin(data.data(), 7000000));
  short_read.invalidate_read(6000001);
  for (int i = 1; i <= 200; ++i)
    short_read.offer(mic.data(), ref.data(), 320, 7000000 + i * 20000, true);
  assert(short_read.ready());
  short_read.invalidate_read(11020000);
  assert(short_read.ready() && !short_read.failed());
  assert(short_read.take().frames == SensePcmWindow::kFrames);
  // Reject invalid clock values before subtracting callback duration.
  SensePcmWindow edge;
  for (auto end_us : {std::numeric_limits<std::int64_t>::min(), std::int64_t{0}}) {
    assert(edge.begin(data.data(), 1000000));
    edge.offer(mic.data(), ref.data(), 320, end_us, true);
    assert(edge.failed() && edge.frames_received() == 0 && !edge.ready());
    assert(edge.discard() == data.data());
  }
  // A valid short callback near the clock's upper limit must not overflow
  // while applying the allowed scheduling-overlap tolerance.
  const auto clock_max = std::numeric_limits<std::int64_t>::max();
  assert(edge.begin(data.data(), clock_max - 5000));
  edge.offer(mic.data(), ref.data(), 16, clock_max - 1000, true);
  edge.offer(mic.data(), ref.data(), 16, clock_max, true);
  assert(!edge.failed() && edge.frames_received() == 32);
  assert(edge.discard() == data.data());
  for (auto rate : {8000U, 12000U, 16000U, 24000U, 32000U, 44100U, 48000U}) {
    stress_capture_clock(rate, 0);
  }
  stress_capture_clock(16000, 180000);
  stress_capture_clock(16000, -10000);
  return 0;
}
