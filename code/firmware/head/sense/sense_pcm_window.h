#pragma once

// A single consent-gated stereo PCM16 calibration window. The real Sense
// Xiaozhi codec supplies simultaneous microphone and AEC reference frames.
// Memory ownership stays with the codec/HTTP caller, not this view class.
// No second mic reader, persistence, speech, or motor authority.

#include <algorithm>
#include <cstddef>
#include <cstdint>

namespace desk_robot {

class SensePcmWindow {
 public:
  static constexpr std::uint32_t kSampleRate = 16000;
  static constexpr std::uint32_t kChannels = 2;
  static constexpr std::uint32_t kFrames = 4 * kSampleRate;
  static constexpr std::size_t kBytes =
      std::size_t{kFrames} * kChannels * sizeof(std::int16_t);
  // Timestamp validation for the *calibration recording*, not a runtime
  // microphone latency budget. Large stalled reads distort acoustic lag
  // even if 64,000 PCM samples eventually arrive in the output buffer.
  static constexpr std::int64_t kMaxCallbackJitterUs = 40'000;
  static constexpr std::int64_t kMaxWindowDriftUs = 80'000;

  struct Complete {
    std::int16_t* interleaved = nullptr;
    std::uint32_t frames = 0;
    std::int64_t first_sample_us = 0;
    std::int64_t last_sample_us = 0;
  };

  bool begin(std::int16_t* storage, std::int64_t request_us) noexcept {
    if (storage == nullptr || request_us <= 0 || storage_ != nullptr)
      return false;
    storage_ = storage;
    requested_us_ = request_us;
    received_ = 0;
    first_sample_us_ = 0;
    last_sample_us_ = 0;
    failed_ = false;
    ready_ = false;
    reference_nonzero_seen_ = false;
    microphone_nonzero_seen_ = false;
    return true;
  }

  void offer(const std::int16_t* mic, const std::int16_t* reference,
             std::uint32_t frames, std::int64_t end_us,
             bool reference_valid) noexcept {
    if (storage_ == nullptr || ready_ || failed_) return;
    // A PDM Read may have started before the authenticated bench START.
    // Never save pre-consent microphone samples merely because that blocking
    // callback finished after START. Drop the whole overlapping callback;
    // the next fresh callback begins the four-second source window.
    if (first_sample_us_ == 0 && frames > 0 && frames <= 2048 &&
        end_us - (std::int64_t{frames} * 1'000'000 / kSampleRate) <
            requested_us_) return;
    // Completion timestamps are host-clock estimates, not true PDM
    // per-sample timestamps. Allow 2 ms of scheduler jitter, but reject a
    // larger inferred overlap: it duplicates previously captured samples
    // while still increasing the four-second window's frame count.
    const std::int64_t callback_us =
        std::int64_t{frames} * 1'000'000 / kSampleRate;
    if (!mic || !reference || frames == 0 || frames > 2048 ||
        !reference_valid || end_us <= requested_us_ ||
        end_us - requested_us_ > 6'000'000 ||
        (last_sample_us_ != 0 &&
         (end_us <= last_sample_us_ ||
          end_us - last_sample_us_ >
              callback_us + kMaxCallbackJitterUs ||
          end_us - callback_us + 2'000 < last_sample_us_)) ||
        (last_sample_us_ == 0 && end_us - requested_us_ > 500'000)) {
      failed_ = true;
      return;
    }
    if (first_sample_us_ == 0) {
      first_sample_us_ = end_us -
          (std::int64_t{frames} * 1'000'000 / kSampleRate);
    }
    const std::uint32_t accepted =
        std::min(frames, kFrames - received_);
    // The last codec read may contain more samples than the remaining
    // four-second capture window. Never timestamp unrecorded tail samples
    // as if they were in the WAV. That would bias physical AEC delay and
    // drift measurements despite an otherwise correct PCM buffer.
    const std::int64_t accepted_end_us = end_us -
        (std::int64_t{frames - accepted} * 1'000'000 / kSampleRate);
    if (accepted_end_us <= first_sample_us_ ||
        (last_sample_us_ && accepted_end_us <= last_sample_us_)) {
      failed_ = true;
      return;
    }
    for (std::uint32_t i = 0; i < accepted; ++i) {
      storage_[2 * (received_ + i)] = mic[i];
      storage_[2 * (received_ + i) + 1] = reference[i];
      // An I2S frame count can advance while the entire transmitted
      // reference is digital silence (e.g. muted gain or silent TTS).
      // Preserve the exact all-zero screening rule; acoustic quality and
      // adequate excitation are still verified by the offline estimator.
      reference_nonzero_seen_ |= reference[i] != 0;
      // A PDM callback with the expected length can still carry an
      // entirely zeroed/disconnected microphone. Refuse that unusable
      // four-second measurement without imposing an unmeasured dB gate.
      microphone_nonzero_seen_ |= mic[i] != 0;
    }
    received_ += accepted;
    last_sample_us_ = accepted_end_us;
    if (received_ == kFrames) {
      // A full byte count does not prove an uninterrupted four seconds.
      // Short missing intervals can each fit the per-read jitter budget,
      // while collectively making the source capture unreliable.
      const auto elapsed = last_sample_us_ - first_sample_us_;
      const auto expected = std::int64_t{kFrames} * 1'000'000 / kSampleRate;
      if (elapsed < expected - kMaxWindowDriftUs ||
          elapsed > expected + kMaxWindowDriftUs ||
          !reference_nonzero_seen_ || !microphone_nonzero_seen_) {
        failed_ = true;
      } else {
        ready_ = true;
      }
    }
  }

  bool ready() const noexcept { return ready_ && !failed_; }
  bool failed() const noexcept { return failed_; }
  bool occupied() const noexcept { return storage_ != nullptr; }
  std::uint32_t frames_received() const noexcept { return received_; }

  Complete take() noexcept {
    if (!ready()) return {};
    Complete out{storage_, received_, first_sample_us_, last_sample_us_};
    reset();
    return out;
  }

  // Returns the caller's allocation for mandatory secure wipe and release.
  std::int16_t* discard() noexcept {
    auto* pointer = storage_;
    reset();
    return pointer;
  }

 private:
  void reset() noexcept {
    storage_ = nullptr;
    requested_us_ = 0;
    received_ = 0;
    first_sample_us_ = 0;
    last_sample_us_ = 0;
    ready_ = false;
    failed_ = false;
    reference_nonzero_seen_ = false;
    microphone_nonzero_seen_ = false;
  }

  std::int16_t* storage_ = nullptr;
  std::uint32_t received_ = 0;
  std::int64_t requested_us_ = 0;
  std::int64_t first_sample_us_ = 0;
  std::int64_t last_sample_us_ = 0;
  bool ready_ = false;
  bool failed_ = false;
  bool reference_nonzero_seen_ = false;
  bool microphone_nonzero_seen_ = false;
};

}  // namespace desk_robot
