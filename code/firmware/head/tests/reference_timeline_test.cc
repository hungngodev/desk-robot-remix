#include "reference_timeline.h"

#include <cstdint>
#include <iostream>
#include <limits>
#include <stdexcept>

#define CHECK(condition) do { \
  if (!(condition)) throw std::runtime_error(#condition); \
} while (false)

using desk_robot::PlaybackReferenceClock;

static void continuous_speech_keeps_one_to_one_time(int cadence_ms) {
  PlaybackReferenceClock clock;
  std::uint64_t published = 0;
  constexpr std::int64_t kDurationUs = 60000000;
  constexpr int kOutputFrames = 1920;  // 60 ms at 32 kHz.
  constexpr std::uint64_t kReferenceFrames = 960;  // 60 ms at 16 kHz.
  for (std::int64_t now = 0; now < kDurationUs;
       now += static_cast<std::int64_t>(cadence_ms) * 1000) {
    published += clock.silence_frames(now, 16384);
    if (now % 60000 == 0) {
      clock.accepted_output_frames(kOutputFrames);
      published += kReferenceFrames;
    }
  }
  CHECK(published == 960000ULL);
  CHECK(clock.represented_end_us() == kDurationUs);
}

static void idle_gap_and_interrupt_are_never_double_counted() {
  PlaybackReferenceClock clock;
  CHECK(clock.silence_frames(1000000, 16384) == 0);
  clock.accepted_output_frames(1920);  // Already represents up to t = 1.06s.
  CHECK(clock.represented_end_us() == 1060000);
  CHECK(clock.silence_frames(1010000, 16384) == 0);
  CHECK(clock.silence_frames(1050000, 16384) == 0);
  CHECK(clock.silence_frames(1060000, 16384) == 0);
  CHECK(clock.silence_frames(1110000, 16384) == 800);
  CHECK(clock.silence_frames(1110000, 16384) == 0);
  CHECK(clock.silence_frames(1120000, 16384) == 160);

  // Cancellation erases the logical timeline as well as the PCM ring.
  clock.reset();
  CHECK(clock.represented_end_us() == 0);
  CHECK(clock.silence_frames(2000000, 16384) == 0);
  clock.accepted_output_frames(1920);
  CHECK(clock.silence_frames(2020000, 16384) == 0);
}

static void decoder_ahead_of_playback_preserves_queued_reference() {
  PlaybackReferenceClock clock;
  // Two 60 ms Opus chunks may decode only 10 ms apart. PCM accepted by
  // I2S is already represented through 120 ms of future playback. Resetting
  // the reference clock to the second callback time would lose the 50 ms
  // queued interval and inject silence into speech that was already queued.
  CHECK(clock.silence_frames(1000000, 16384) == 0);
  clock.accepted_output_frames(1920);
  CHECK(clock.represented_end_us() == 1060000);
  CHECK(clock.silence_frames(1010000, 16384) == 0);
  clock.accepted_output_frames(1920);
  CHECK(clock.represented_end_us() == 1120000);
  CHECK(clock.silence_frames(1080000, 16384) == 0);
  CHECK(clock.silence_frames(1120000, 16384) == 0);
  CHECK(clock.silence_frames(1130000, 16384) == 160);
  CHECK(clock.silence_frames(1130000, 16384) == 0);
}

static void queued_output_is_not_premature_microphone_reference() {
  PlaybackReferenceClock clock;
  CHECK(clock.silence_frames(1000000, 16384) == 0);
  clock.accepted_output_frames(1920);
  CHECK(clock.future_reference_frames(1000000, 16384) == 960);
  CHECK(clock.future_reference_frames(1010000, 16384) == 800);
  clock.silence_frames(1010000, 16384);
  clock.accepted_output_frames(1920);
  CHECK(clock.represented_end_us() == 1120000);
  CHECK(clock.future_reference_frames(1020000, 16384) == 1600);
  CHECK(clock.future_reference_frames(1080000, 16384) == 640);
  CHECK(clock.future_reference_frames(1120000, 16384) == 0);
  CHECK(clock.future_reference_frames(1130000, 16384) == 0);
  clock.accepted_output_frames(32000);
  clock.accepted_output_frames(32000);
  CHECK(clock.future_reference_frames(1120000, 16384) == 16384);
  CHECK(clock.future_reference_frames(1120000, 10) == 10);
  clock.reset();
  CHECK(clock.future_reference_frames(1120000, 16384) == 0);
}

static void late_opus_chunk_accounts_for_real_gap_once() {
  PlaybackReferenceClock clock;
  CHECK(clock.silence_frames(1000000, 16384) == 0);
  clock.accepted_output_frames(1920);  // PCM represents 1.00..1.06 s.
  CHECK(clock.silence_frames(1070000, 16384) == 160);
  // The next chunk arrives at 1.10 s, so 30 ms more silence is needed
  // after the previous 10 ms gap. Neither portion may be doubled.
  CHECK(clock.silence_frames(1100000, 16384) == 480);
  clock.accepted_output_frames(1920);
  CHECK(clock.represented_end_us() == 1160000);
  CHECK(clock.silence_frames(1130000, 16384) == 0);
  CHECK(clock.silence_frames(1160000, 16384) == 0);
  CHECK(clock.silence_frames(1170000, 16384) == 160);
}

static void irregular_idle_cadence_retains_fractional_reference_samples() {
  PlaybackReferenceClock clock;
  constexpr std::int64_t kStartUs = 1000000;
  constexpr std::int64_t kReadUs = 10007;
  constexpr int kReads = 6000;
  CHECK(clock.silence_frames(kStartUs, 16384) == 0);
  std::uint64_t total = 0;
  for (int n = 1; n <= kReads; ++n) {
    total += clock.silence_frames(kStartUs + n * kReadUs, 16384);
  }
  const auto expected = static_cast<std::uint64_t>(
      kReads * kReadUs * PlaybackReferenceClock::kReferenceRate / 1000000U);
  CHECK(total == expected);
  CHECK(total == 960672ULL);  // Prior per-callback truncation returned 960000.
  CHECK(clock.represented_end_us() == kStartUs + kReads * kReadUs);
}

static void short_i2s_writes_preserve_submicrosecond_playback_time() {
  PlaybackReferenceClock clock;
  CHECK(clock.silence_frames(1000000, 16384) == 0);
  for (int n = 0; n < 32000; ++n) clock.accepted_output_frames(1);
  CHECK(clock.represented_end_us() == 2000000);
  CHECK(clock.silence_frames(2000000, 16384) == 0);
  CHECK(clock.silence_frames(2010000, 16384) == 160);
}

static void reset_retires_fractional_timing_residue() {
  PlaybackReferenceClock clock;
  CHECK(clock.silence_frames(1000000, 16384) == 0);
  CHECK(clock.silence_frames(1010007, 16384) == 160);
  clock.accepted_output_frames(1);
  clock.reset();
  CHECK(clock.silence_frames(2000000, 16384) == 0);
  CHECK(clock.silence_frames(2010007, 16384) == 160);
  clock.accepted_output_frames(32000);
  CHECK(clock.represented_end_us() == 3010007);
}

static void zero_timestamp_is_valid_clock_origin() {
  PlaybackReferenceClock clock;
  CHECK(clock.silence_frames(0, 16384) == 0);
  // Zero is a valid monotonic clock origin, not an uninitialized sentinel.
  CHECK(clock.silence_frames(10000, 16384) == 160);
  CHECK(clock.silence_frames(20000, 16384) == 160);
  clock.reset();
  CHECK(clock.silence_frames(0, 16384) == 0);
  CHECK(clock.silence_frames(10000, 16384) == 160);
  // A chunk accepted before an explicit reference read still initializes
  // the timeline and cannot be discarded by the next silence callback.
  PlaybackReferenceClock output_first;
  output_first.accepted_output_frames(320);
  CHECK(output_first.represented_end_us() == 10000);
  CHECK(output_first.silence_frames(20000, 16384) == 160);
}

static void huge_idle_gaps_are_bounded() {
  PlaybackReferenceClock clock;
  CHECK(clock.silence_frames(1000000, 16384) == 0);
  CHECK(clock.silence_frames(12000000, 16384) == 16384);
  CHECK(clock.silence_frames(12000000, 16384) == 0);
}

static void timestamp_and_cap_extremes_do_not_overflow() {
  constexpr auto lo = std::numeric_limits<std::int64_t>::min();
  constexpr auto hi = std::numeric_limits<std::int64_t>::max();
  constexpr auto cap = std::numeric_limits<std::uint64_t>::max();
  PlaybackReferenceClock clock;
  CHECK(clock.silence_frames(lo, cap) == 0);
  CHECK(clock.silence_frames(hi, cap) ==
        (cap / 1000000U) * 16000U + (cap % 1000000U) * 16000U / 1000000U);
  CHECK(clock.future_reference_frames(0, cap) ==
        (static_cast<std::uint64_t>(hi) / 1000000U) * 16000U +
        ((static_cast<std::uint64_t>(hi) % 1000000U) * 16000U + 999999U) /
            1000000U);
  clock.accepted_output_frames(1);
  CHECK(clock.represented_end_us() == hi);
  clock.reset();
  CHECK(clock.silence_frames(lo, 16384) == 0);
  CHECK(clock.silence_frames(hi, 16384) == 16384);
}

int main() {
  try {
    for (int cadence_ms : {10, 20, 30, 60}) {
      continuous_speech_keeps_one_to_one_time(cadence_ms);
    }
    idle_gap_and_interrupt_are_never_double_counted();
    decoder_ahead_of_playback_preserves_queued_reference();
    queued_output_is_not_premature_microphone_reference();
    late_opus_chunk_accounts_for_real_gap_once();
    huge_idle_gaps_are_bounded();
    timestamp_and_cap_extremes_do_not_overflow();
    zero_timestamp_is_valid_clock_origin();
    irregular_idle_cadence_retains_fractional_reference_samples();
    short_i2s_writes_preserve_submicrosecond_playback_time();
    reset_retires_fractional_timing_residue();
    std::cout << "PASS actual Sense playback reference time accounting\n";
  } catch (const std::exception& exc) {
    std::cerr << "FAIL " << exc.what() << "\n";
    return 1;
  }
  return 0;
}
