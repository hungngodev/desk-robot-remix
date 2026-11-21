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
#include "sdkconfig.h"

#include <array>
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

    // Read-only integrity counters for A2 diagnostics, not an acoustic pass.
    // Counters persist across speech cancellation. A physical qualification
    // requires an independently measured echo/double-talk trial.
    struct ReferenceDiagnostics {
        uint32_t underflow_reads;
        uint32_t overwrite_reads;
        uint32_t discarded_stale_writes;
        uint32_t short_output_writes;
        bool integrity_failed;
    };
    ReferenceDiagnostics GetReferenceDiagnostics();

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
    static_assert(kSpeakerRate % kMicRate == 0, "AEC decimation ratio must be integral");
    static_assert(kMicRate == desk_robot::PlaybackReferenceClock::kReferenceRate,
                  "AEC ring clock must match microphone rate");
    static_assert(kSpeakerRate == desk_robot::PlaybackReferenceClock::kOutputRate,
                  "AEC output clock must match speaker rate");
    // Per-unit ESP-IDF private build setting, default 90 ms only as a bench
    // starting point. It is not a physical acoustic calibration.
    static constexpr uint32_t kDelaySamples =
        CONFIG_DESK_ROBOT_AEC_DELAY_MS * (kMicRate / 1000);
    static constexpr uint32_t kMaxGapSamples = kRingSize;
    static_assert((kRingSize & (kRingSize - 1)) == 0);
    // Reuse fixed bounded mic/reference frame scratch buffers instead of
    // allocating twice on every realtime 16 kHz microphone callback.
    // One capture reader owns the scratch buffers at a time.
    static constexpr int kMaxReadFrames = 2048;
    std::mutex input_read_mutex_;
    std::array<int16_t, kMaxReadFrames> microphone_frame_{};
    std::array<int16_t, kMaxReadFrames> reference_frame_{};
    std::mutex reference_mutex_;
    std::array<int16_t, kRingSize> reference_{};
    uint64_t write_index_ = 0;
    // Bump when playback is cancelled/reset. A blocked I2S writer must not
    // publish its old accepted frames after ClearReference() reset the ring.
    // Guarded by reference_mutex_, not a competing audio task/driver.
    uint64_t reference_generation_ = 0;
    uint32_t stale_publish_discards_ = 0;
    // I2S timeout/short output cannot be counted as fully delivered speech.
    uint32_t short_output_writes_ = 0;
    // Silence-only reference on startup/reset is expected briefly. Count
    // missing windows and warn only on prolonged consecutive underflow.
    uint32_t missing_reference_reads_ = 0;
    uint32_t consecutive_missing_reference_reads_ = 0;
    uint32_t reference_overwrite_reads_ = 0;
    bool reference_integrity_failed_ = false;
    bool reference_read_seen_ = false;
    uint64_t last_reference_read_write_index_ = 0;
    desk_robot::PlaybackReferenceClock reference_clock_{};
    int16_t filter_last1_ = 0;
    int16_t filter_last2_ = 0;
    int16_t last_filtered_ = 0;
    float phase_ = 0.0f;

    void FillSilenceLocked(int64_t now_us);
    void PushLocked(int16_t sample);
    void PublishAcceptedLocked(const int16_t* source, int samples, int volume,
                               int64_t now_us);
    bool ReadReferenceLocked(int16_t* dest, int frames, int64_t now_us);
};
