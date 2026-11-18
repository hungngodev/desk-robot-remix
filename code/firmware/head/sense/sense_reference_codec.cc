#include "sense_reference_codec.h"

#include <algorithm>
#include <cmath>
#include <esp_timer.h>
#include <esp_log.h>

SenseReferenceCodec::SenseReferenceCodec(
    int microphone_rate, int speaker_rate, gpio_num_t speaker_bclk,
    gpio_num_t speaker_lrck, gpio_num_t speaker_data,
    gpio_num_t microphone_clock, gpio_num_t microphone_data)
    : NoAudioCodecSimplexPdm(microphone_rate, speaker_rate, speaker_bclk,
                             speaker_lrck, speaker_data,
                             microphone_clock, microphone_data) {
    // The existing ESP-SR AFE expects interleaved MIC, REFERENCE samples.
    // Advertise two channels only because Read() below actually fills both.
    input_reference_ = true;
    input_channels_ = 2;
    duplex_ = true;
}

void SenseReferenceCodec::PushLocked(int16_t sample) {
    reference_[write_index_ & (kRingSize - 1)] = sample;
    ++write_index_;
}

void SenseReferenceCodec::FillSilenceLocked(int64_t now_us) {
    // The pure clock is also compiled and exercised by host regression
    // tests. Reads may not replay wall time already represented by PCM.
    const uint64_t sample_gap =
        reference_clock_.silence_frames(now_us, kMaxGapSamples);
    for (uint64_t n = 0; n < sample_gap; ++n) {
        PushLocked(0);
    }
}

void SenseReferenceCodec::PublishAcceptedLocked(
    const int16_t* source, int samples, int volume, int64_t now_us) {
    FillSilenceLocked(now_us);
    // Xiaozhi's NoAudioCodec::Write performs a squared output volume gain.
    // Reference samples must reflect THAT gain, not the unclipped WAV bytes.
    const double ratio = static_cast<double>(volume) / 100.0;
    const double factor = ratio * ratio;
    for (int i = 0; i < samples; ++i) {
        const int32_t scaled = static_cast<int32_t>(
            std::clamp(std::lround(static_cast<double>(source[i]) * factor),
                       -32768L, 32767L));
        // RIO-inspired three tap low pass followed by 2:1 decimation from the
        // MAX98357A-supported 32 kHz output to the 16 kHz PDM AEC reference. Preserve
        // filter and fractional phase across decoder chunk boundaries.
        const int32_t filtered = (static_cast<int32_t>(filter_last2_) +
                                  2 * static_cast<int32_t>(filter_last1_) +
                                  scaled) / 4;
        filter_last2_ = filter_last1_;
        filter_last1_ = static_cast<int16_t>(scaled);
        // The board contract fixes a 32 kHz output and 16 kHz microphone.
        // Each output sample can publish at most one reference sample.
        // A loop would misleadingly suggest unsupported fractional ratios.
        if (phase_ < 1.0f) {
            const int32_t result = static_cast<int32_t>(
                last_filtered_ + (filtered - last_filtered_) * phase_);
            PushLocked(static_cast<int16_t>(std::clamp(result, static_cast<int32_t>(-32768), static_cast<int32_t>(32767))));
            phase_ += static_cast<float>(kSpeakerRate) / kMicRate;
        }
        phase_ -= 1.0f;
        last_filtered_ = static_cast<int16_t>(filtered);
    }
    // The accepted chunk advances the clock by its actual sample duration.
    // Never reset it to the callback time: that would count the same 60 ms
    // of speech again when the 10 ms PDM capture reader fills silence.
    reference_clock_.accepted_output_frames(samples);
}

bool SenseReferenceCodec::ReadReferenceLocked(int16_t* dest, int frames) {
    const uint32_t required = kDelaySamples + static_cast<uint32_t>(frames);
    if (required > kRingSize || write_index_ < required) {
        // A missing reference is silence only, not proof that AEC aligned.
        // Count it without logging inside the audio ring mutex.
        if (missing_reference_reads_ != UINT32_MAX) ++missing_reference_reads_;
        if (consecutive_missing_reference_reads_ != UINT32_MAX)
            ++consecutive_missing_reference_reads_;
        if (consecutive_missing_reference_reads_ >= 32)
            reference_integrity_failed_ = true;
        std::fill_n(dest, frames, 0);
        return false;
    }
    consecutive_missing_reference_reads_ = 0;
    // If playback advanced by a whole ring between microphone reads, the
    // unseen reference interval has been overwritten. Do not align an
    // apparently fresh echo to a reference history that no longer exists.
    // This is conservative: even a long idle period needs realignment.
    const bool lapped = reference_read_seen_ &&
        write_index_ - last_reference_read_write_index_ >= kRingSize;
    last_reference_read_write_index_ = write_index_;
    reference_read_seen_ = true;
    if (lapped) {
        if (reference_overwrite_reads_ != UINT32_MAX) ++reference_overwrite_reads_;
        reference_integrity_failed_ = true;
        std::fill_n(dest, frames, 0);
        return false;
    }
    const uint64_t start = write_index_ - required;
    for (int i = 0; i < frames; ++i) {
        dest[i] = reference_[(start + i) & (kRingSize - 1)];
    }
    return true;
}

int SenseReferenceCodec::Read(int16_t* dest, int samples) {
    if (dest == nullptr || samples <= 0 || samples % 2 ||
        samples > 4096 || input_sample_rate_ != static_cast<int>(kMicRate)) {
        return 0;
    }
    const int frames = samples / 2;
    if (frames > kMaxReadFrames) return 0;
    // The head owns one realtime capture reader. A bounded mutex also
    // prevents concurrent callbacks from corrupting shared frame scratch.
    std::lock_guard<std::mutex> input_lock(input_read_mutex_);
    // Keep microphone/I2S read outside reference_mutex_: it can block for
    // samples and must never prevent output publishing an AEC reference.
    const int mic_read = NoAudioCodecSimplexPdm::Read(microphone_frame_.data(), frames);
    if (mic_read != frames) {
        return 0; // AudioCodec::InputData is boolean; reject partial frames.
    }
    bool reference_ready = false;
    uint32_t consecutive_missing = 0;
    uint32_t overwrite_count = 0;
    bool newly_overwritten = false;
    {
        std::lock_guard<std::mutex> lock(reference_mutex_);
        FillSilenceLocked(esp_timer_get_time());
        const uint32_t previous_overwrites = reference_overwrite_reads_;
        reference_ready = ReadReferenceLocked(reference_frame_.data(), frames);
        consecutive_missing = consecutive_missing_reference_reads_;
        overwrite_count = reference_overwrite_reads_;
        newly_overwritten = overwrite_count != previous_overwrites;
    }
    // Log outside the codec ring mutex only when the counter ADVANCES.
    // Persistent failure state must not flood the audio task's logs.
    if (newly_overwritten &&
        (overwrite_count == 1 || (overwrite_count % 32U) == 0U)) {
        ESP_LOGW("SenseAEC", "reference ring overwritten; %u compromised microphone reads; A2 integrity FAILED",
                 static_cast<unsigned>(overwrite_count));
    }
    // Initial silence after boot/reset is normal. Warn only for a
    // prolonged unavailable reference, at most once per 256 more reads.
    if (!reference_ready && consecutive_missing >= 32 &&
        (consecutive_missing - 32U) % 256U == 0U) {
        ESP_LOGW("SenseAEC", "reference unavailable for %u consecutive microphone reads; AEC alignment unverified",
                 static_cast<unsigned>(consecutive_missing));
    }
    for (int i = 0; i < frames; ++i) {
        dest[2 * i] = microphone_frame_[i];
        dest[2 * i + 1] = reference_frame_[i];
    }
    return samples;
}

int SenseReferenceCodec::Write(const int16_t* data, int samples) {
    if (data == nullptr || samples <= 0 || samples > static_cast<int>(kSpeakerRate) ||
        output_sample_rate_ != static_cast<int>(kSpeakerRate)) {
        return 0;
    }
    const int volume = output_volume_;
    uint64_t started_generation = 0;
    {
        std::lock_guard<std::mutex> lock(reference_mutex_);
        started_generation = reference_generation_;
    }
    // The inherited I2S write can block; never hold reference_mutex_ across it.
    // Reset/urgent barge-in may clear the ring while this old write finishes.
    const int accepted = NoAudioCodec::Write(data, samples);
    bool log_stale = false;
    uint32_t stale_discards = 0;
    if (accepted > 0) {
        std::lock_guard<std::mutex> lock(reference_mutex_);
        if (started_generation == reference_generation_) {
            PublishAcceptedLocked(data, accepted, volume, esp_timer_get_time());
        } else {
            // The physical TX DMA may have accepted some old audio. It must
            // NOT be relabeled as current-generation echo reference.
            if (stale_publish_discards_ != UINT32_MAX) ++stale_publish_discards_;
            stale_discards = stale_publish_discards_;
            reference_integrity_failed_ = true;
            log_stale = stale_discards == 1 || (stale_discards % 32U) == 0;
        }
    }
    if (log_stale) {
        ESP_LOGW("SenseAEC", "discarded stale playback reference after cancellation: %u writes; physical TX silence unverified",
                 static_cast<unsigned>(stale_discards));
    }
    return accepted;
}

void SenseReferenceCodec::ClearReference() {
    std::lock_guard<std::mutex> lock(reference_mutex_);
    // Invalidate writes that entered the inherited blocking I2S path before
    // this reset. Never reset this generation with the ring write index.
    ++reference_generation_;
    consecutive_missing_reference_reads_ = 0;
    reference_read_seen_ = false;
    last_reference_read_write_index_ = 0;
    // Keep lifetime integrity failure and counters across cancellation.
    // A reset is not evidence that an audible stale TX tail vanished.
    reference_.fill(0);
    write_index_ = 0;
    reference_clock_.reset();
    filter_last1_ = 0;
    filter_last2_ = 0;
    last_filtered_ = 0;
    phase_ = 0.0f;
}

SenseReferenceCodec::ReferenceDiagnostics
SenseReferenceCodec::GetReferenceDiagnostics() {
    std::lock_guard<std::mutex> lock(reference_mutex_);
    return ReferenceDiagnostics{
        missing_reference_reads_, reference_overwrite_reads_,
        stale_publish_discards_, reference_integrity_failed_};
}

void SenseReferenceCodec::EnableOutput(bool enable) {
    if (!enable) {
        // Urgent output disable invalidates reference for canceled audio.
        ClearReference();
    }
    NoAudioCodec::EnableOutput(enable);
}
