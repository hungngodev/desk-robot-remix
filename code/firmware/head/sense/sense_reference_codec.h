#pragma once

// Sense-only microphone and speaker reference bridge for Xiaozhi's existing
// ESP-SR AFE. Adapt RIO's playback-reference and stream-resampling pattern
// rather than creating a second independent speech frontend.
// Reused source ideas: https://github.com/mk14ray/RIO-XIAO-ESP32-S3-Gemini-Live-Voice-Assistant
// Pinned baseline: b911305e48ce6a1b75fe6c07fc02f86ad7bfeb0a (MIT).
//
// This is a real PCM reference path, NOT an assertion that the physical
// loudspeaker/microphone acoustic delay has been calibrated or A2 passed.
#include "codecs/no_audio_codec.h"
#include "config.h"  // Selected Sense board AUDIO_*_SAMPLE_RATE contract.
#include "reference_timeline.h"
#include "reference_decimator.h"
#include "sense_speaker_activity.hpp"
#include "sdkconfig.h"
#ifdef CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED
#include "sense_pcm_window.h"
#include "esp_timer.h"
#endif

#include <array>
#include <atomic>
#include <cstdint>
#include <mutex>

class SenseReferenceCodec final : public NoAudioCodecSimplexPdm {
public:
    SenseReferenceCodec(int microphone_rate, int speaker_rate,
                        gpio_num_t speaker_bclk, gpio_num_t speaker_lrck,
                        gpio_num_t speaker_data, gpio_num_t microphone_clock,
                        gpio_num_t microphone_data);

    // Urgent output reset is driven by the application playback flush event.
    // i2s_channel_disable()/enable() remains owned by the inherited codec.
    void ClearReference();
    void EnableOutput(bool enable) override;

    // Physical BOOT consent wins before queued Xiaozhi audio tasks unwind.
    // This gates the actual PDM samples on the canonical codec only.
    void SetMicrophonePrivacyMuted(bool muted) {
        const bool previous = microphone_privacy_muted_.exchange(
            muted, std::memory_order_acq_rel);
        if (previous != muted) {
            microphone_privacy_epoch_.fetch_add(1, std::memory_order_acq_rel);
        }
#ifdef CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED
        // A physical mute also destroys any private raw-PDM bench recording.
        // The atomic flag is set BEFORE waiting for its bounded RAM owner.
        if (muted) AbortBenchPcmCapture();
#endif
    }

    // Read-only integrity counters for A2 diagnostics, not an acoustic pass.
    // Counters persist across speech cancellation. A physical qualification
    // requires an independently measured echo/double-talk trial.
    struct ReferenceDiagnostics {
        uint32_t underflow_reads;
        uint32_t overwrite_reads;
        uint32_t discarded_stale_writes;
        uint32_t short_output_writes;
        uint32_t short_input_reads;
        uint32_t microphone_frames_read;
        uint32_t speaker_frames_accepted;
        // BOOT privacy is measured at the real PDM owner, not a GUI guess.
        bool microphone_privacy_muted;
        uint32_t microphone_privacy_epoch;
        bool integrity_failed;
    };
    ReferenceDiagnostics GetReferenceDiagnostics();
#ifdef CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED
    // A private opt-in build and one authenticated operator request are
    // required. This reuses the Xiaozhi 16 kHz mic/reference Read callback.
    struct BenchCaptureProgress {
        bool active;
        bool ready;
        bool failed;
        uint32_t frames;
        uint64_t generation;
        // Activity was observed before the final captured microphone frame,
        // not on a later HTTP diagnostics poll. Never acoustic playback ACK.
        bool speaker_activity_in_window;
    };
    // Only the physical BOOT calibration gesture may issue this one-use grant.
    void GrantBenchPcmConsent();
    bool BeginBenchPcmCapture(uint32_t expected_privacy_epoch);
    // A physical BOOT mute or playback cancellation invalidates any
    // asynchronous raw PCM transfer, even after its buffer was taken.
    uint64_t BenchPcmGeneration() const noexcept {
        return bench_capture_generation_.load(std::memory_order_acquire);
    }
    void EndBenchPcmTransfer();
    BenchCaptureProgress GetBenchPcmProgress();
    desk_robot::SensePcmWindow::Complete TakeBenchPcmCapture(uint64_t expected_generation);
    void AbortBenchPcmCapture(bool revoke_consent = true);
    static void ReleaseBenchPcmCapture(int16_t* data);
#endif

protected:
    int Read(int16_t* dest, int samples) override;
    int Write(const int16_t* data, int samples) override;

private:
    static constexpr uint32_t kRingSize = 16384;   // 1024 ms at 16 kHz
    static constexpr uint32_t kMicRate = 16000;
    static constexpr uint32_t kSpeakerRate = 32000;  // MAX98357A supported clock
    // Fail the actual Sense firmware build if a board pin/audio change drifts
    // away from the reference path. Otherwise Write() silently returns zero.
    static_assert(AUDIO_INPUT_SAMPLE_RATE == kMicRate,
                  "Sense AEC microphone rate differs from the active board");
    static_assert(AUDIO_OUTPUT_SAMPLE_RATE == kSpeakerRate,
                  "Sense AEC speaker rate differs from the active board");
    static_assert(kSpeakerRate == kSenseTxScratchSamples,
                  "Sense TX scratch must preserve the wrapper's bounded write size");
    static_assert(kSpeakerRate == 2 * kMicRate, "AEC decimation ratio must be 2:1");
    static_assert(kMicRate == desk_robot::PlaybackReferenceClock::kReferenceRate,
                  "AEC ring clock must match microphone rate");
    static_assert(kSpeakerRate == desk_robot::PlaybackReferenceClock::kOutputRate,
                  "AEC output clock must match speaker rate");
    // Per-unit ESP-IDF private build setting, default 90 ms only as a bench
    // starting point. It is not a physical acoustic calibration.
    static constexpr uint32_t kDelaySamples =
        CONFIG_DESK_ROBOT_AEC_DELAY_MS * (kMicRate / 1000);
#ifdef CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED
    // The captured digital reference already includes this delay. Require
    // zero for measuring absolute acoustic lag rather than residual lag.
    static_assert(kDelaySamples == 0,
                  "Raw acoustic calibration capture needs AEC delay 0 ms");
#endif
    static constexpr uint32_t kMaxGapSamples = kRingSize;
    static_assert((kRingSize & (kRingSize - 1)) == 0);
    // Reuse fixed bounded mic/reference frame scratch buffers instead of
    // allocating twice on every realtime 16 kHz microphone callback.
    // One capture reader owns the scratch buffers at a time.
    static constexpr int kMaxReadFrames = 2048;
    std::atomic<bool> microphone_privacy_muted_{false};
    std::atomic<uint32_t> microphone_privacy_epoch_{0};
    std::mutex input_read_mutex_;
    // Retain exclusive ownership of submitted PCM through reference publication.
    // Cancellation never waits on this mutex; it fences the generation instead.
    std::mutex output_write_mutex_;
    std::array<int16_t, kMaxReadFrames> microphone_frame_{};
    std::array<int16_t, kMaxReadFrames> reference_frame_{};
    std::mutex reference_mutex_;
#ifdef CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED
    std::mutex bench_mutex_;
    desk_robot::FreshBenchPcmConsent bench_consent_{};
    std::atomic<uint64_t> bench_capture_generation_{0};
    bool bench_transfer_active_ = false;  // one RAM transfer at a time
    desk_robot::SensePcmWindow bench_window_{};
    desk_robot::SenseSpeakerActivity::Snapshot bench_speaker_at_start_{};
    bool bench_speaker_activity_in_window_ = false;
    esp_timer_handle_t bench_expiry_timer_ = nullptr;
    int64_t bench_started_us_ = 0;
    static void BenchPcmExpiry(void* context);
#endif
    std::array<int16_t, kRingSize> reference_{};
    uint64_t write_index_ = 0;
    // Bump when playback is cancelled/reset. A blocked I2S writer must not
    // publish its old accepted frames after ClearReference() reset the ring.
    // Guarded by reference_mutex_, not a competing audio task/driver.
    desk_robot::SenseSpeakerActivity speaker_activity_{};
    uint32_t stale_publish_discards_ = 0;
    // I2S timeout/short output cannot be counted as fully delivered speech.
    uint32_t short_output_writes_ = 0;
    // Actual PDM driver errors/short reads, distinct from reference overwrites.
    uint32_t short_input_reads_ = 0;
    // Driver read/write progress, not proof of microphone acoustic quality
    // or speaker playback. Persist across cancellation for a live bench.
    uint32_t microphone_frames_read_ = 0;
    uint32_t speaker_frames_accepted_ = 0;
    // Silence-only reference on startup/reset is expected briefly. Count
    // missing windows and latch prolonged underflow for diagnostic polling.
    uint32_t missing_reference_reads_ = 0;
    uint32_t consecutive_missing_reference_reads_ = 0;
    uint32_t reference_overwrite_reads_ = 0;
    bool reference_integrity_failed_ = false;
    bool reference_read_seen_ = false;
    uint64_t last_reference_read_write_index_ = 0;
    desk_robot::PlaybackReferenceClock reference_clock_{};
    desk_robot::ReferenceDecimator reference_decimator_{};

    void FillSilenceLocked(int64_t now_us);
    void PushLocked(int16_t sample);
    void PublishAcceptedLocked(const int32_t* source, int samples, int64_t now_us);
    bool ReadReferenceLocked(int16_t* dest, int frames, int64_t now_us);
};
