#include "sense_reference_codec.h"

#include <algorithm>
#include <cmath>
#include <esp_timer.h>
#include <esp_log.h>
#ifdef CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED
#include <esp_heap_caps.h>
#include <cstddef>
#endif

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

bool SenseReferenceCodec::ReadReferenceLocked(int16_t* dest, int frames,
                                              int64_t now_us) {
    // A fast decoder can publish two accepted 60 ms Opus frames only 10 ms
    // apart. Reference samples at the ring head may therefore represent
    // output that the speaker has not played yet. Project the reference
    // end back onto this microphone capture timestamp BEFORE applying the
    // per-unit acoustic delay. Hardware acoustic trials remain required.
    const uint64_t future = reference_clock_.future_reference_frames(
        now_us, kRingSize);
    const uint64_t required =
        static_cast<uint64_t>(kDelaySamples) + frames + future;
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
    const uint32_t privacy_epoch = microphone_privacy_epoch_.load(
        std::memory_order_acquire);
    if (microphone_privacy_muted_.load(std::memory_order_acquire)) return 0;
    // The head owns one realtime capture reader. A bounded mutex also
    // prevents concurrent callbacks from corrupting shared frame scratch.
    std::lock_guard<std::mutex> input_lock(input_read_mutex_);
    // Consent may have changed while this callback waited for the reader
    // mutex. Do not start a new hardware read on a revoked capture epoch.
    if (microphone_privacy_muted_.load(std::memory_order_acquire) ||
        privacy_epoch != microphone_privacy_epoch_.load(std::memory_order_acquire)) {
        return 0;
    }
    // Keep microphone/I2S read outside reference_mutex_: it can block for
    // samples and must never prevent output publishing an AEC reference.
    const int mic_read = NoAudioCodecSimplexPdm::Read(microphone_frame_.data(), frames);
    if (mic_read != frames) {
#ifdef CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED
        // A known missing PDM interval cannot be treated as scheduler jitter.
        // Timestamp the failure before waiting for the bench owner; a late
        // callback from before the current START cannot poison its window.
        const int64_t failed_read_us = esp_timer_get_time();
        {
            std::lock_guard<std::mutex> lock(bench_mutex_);
            bench_window_.invalidate_read(failed_read_us);
        }
#endif
        // An error or short PDM read can still have written raw microphone PCM.
        std::fill_n(microphone_frame_.begin(), frames, 0);
        return 0; // AudioCodec::InputData is boolean; reject partial frames.
    }
    // Discard a PDM read that crossed a physical BOOT mute/unmute epoch.
    if (microphone_privacy_muted_.load(std::memory_order_acquire) ||
        privacy_epoch != microphone_privacy_epoch_.load(std::memory_order_acquire)) {
        std::fill_n(microphone_frame_.begin(), frames, 0);
        return 0;
    }
    // Timestamp the completed PDM read once, before reference work or task
    // scheduling can add an unrelated delay. This is a source-clock estimate,
    // not a hardware exposure or acoustic speaker-playback receipt.
    const int64_t capture_end_us = esp_timer_get_time();
    bool reference_ready = false;
    uint32_t consecutive_missing = 0;
    uint32_t overwrite_count = 0;
    bool newly_overwritten = false;
    {
        std::lock_guard<std::mutex> lock(reference_mutex_);
        // Only successful, complete microphone reads advance actual input
        // activity. Counting attempted reads would fake an active PDM stream.
        microphone_frames_read_ += std::min(
            static_cast<uint32_t>(frames), UINT32_MAX - microphone_frames_read_);
        FillSilenceLocked(capture_end_us);
        const uint32_t previous_overwrites = reference_overwrite_reads_;
        reference_ready = ReadReferenceLocked(
            reference_frame_.data(), frames, capture_end_us);
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
    // Check again after mixing AEC channels, before any raw PCM capture.
    if (microphone_privacy_muted_.load(std::memory_order_acquire) ||
        privacy_epoch != microphone_privacy_epoch_.load(std::memory_order_acquire)) {
        std::fill_n(dest, samples, 0);
        std::fill_n(microphone_frame_.begin(), frames, 0);
        return 0;
    }
#ifdef CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED
    {
        // One optional RAM-only calibration listener of ALREADY sampled mic
        // and reference. No second PDM/I2S reader or audio network service.
        std::lock_guard<std::mutex> lock(bench_mutex_);
        if (!microphone_privacy_muted_.load(std::memory_order_acquire) &&
            privacy_epoch == microphone_privacy_epoch_.load(std::memory_order_acquire)) {
            const bool already_ready = bench_window_.ready();
            const bool had_frames = bench_window_.frames_received() != 0;
            bench_window_.offer(microphone_frame_.data(), reference_frame_.data(),
                                static_cast<uint32_t>(frames), capture_end_us,
                                reference_ready);
            if (!had_frames && bench_window_.frames_received() != 0) {
                std::lock_guard<std::mutex> reference_lock(reference_mutex_);
                speaker_activity_.FenceWindowStart(
                    bench_speaker_at_start_, bench_window_.first_sample_us());
            }
            // Snapshot activity at the final MIC callback. Later speaker
            // writes after raw capture completion cannot qualify this window.
            if (!already_ready && bench_window_.ready()) {
                std::lock_guard<std::mutex> reference_lock(reference_mutex_);
                bench_speaker_activity_in_window_ =
                    speaker_activity_.AdvancedSince(
                        bench_speaker_at_start_, bench_window_.last_sample_us());
            }
        }
    }
#endif
    // BOOT may arrive during a bounded private capture copy. The mute
    // setter invalidates the buffer and these samples never reach Opus.
    if (microphone_privacy_muted_.load(std::memory_order_acquire) ||
        privacy_epoch != microphone_privacy_epoch_.load(std::memory_order_acquire)) {
        std::fill_n(dest, samples, 0);
        std::fill_n(microphone_frame_.begin(), frames, 0);
        return 0;
    }
    return samples;
}

int SenseReferenceCodec::Write(const int16_t* data, int samples) {
    if (data == nullptr || samples <= 0 || samples > static_cast<int>(kSpeakerRate) ||
        output_sample_rate_ != static_cast<int>(kSpeakerRate)) {
        return 0;
    }
    // Match the selected Sense-only Xiaozhi I2S gain clamp exactly.
    // A malformed saved volume must not overflow PCM32 or the echo reference.
    const int volume = std::clamp(output_volume_, 0, 100);
    uint64_t started_generation = 0;
    {
        std::lock_guard<std::mutex> lock(reference_mutex_);
        started_generation = speaker_activity_.generation();
    }
    // The selected Sense overlay already bounds the pinned Xiaozhi writer's
    // I2S wait. Preserve its mutex, squared-volume PCM conversion and sole
    // speaker owner rather than maintaining a second codec implementation.
    const int accepted = NoAudioCodec::Write(data, samples);
    bool log_stale = false;
    uint32_t stale_discards = 0;
    bool log_short = false;
    uint32_t short_writes = 0;
    {
        std::lock_guard<std::mutex> lock(reference_mutex_);
        // Accepted into I2S does not establish audible playback or DMA
        // drain. It is only a required software activity signal for A2.
        if (accepted > 0) {
            speaker_frames_accepted_ += std::min(
                static_cast<uint32_t>(accepted),
                UINT32_MAX - speaker_frames_accepted_);
        }
        // The pinned AudioCodec::OutputData discards Write's return value.
        // Never let a timed-out/partial Sense TX masquerade as complete
        // speech or a qualified echo reference, even on a clean generation.
        if (accepted != samples) {
            if (short_output_writes_ != UINT32_MAX) ++short_output_writes_;
            short_writes = short_output_writes_;
            reference_integrity_failed_ = true;
            log_short = short_writes == 1 || (short_writes % 32U) == 0U;
        }
        const int64_t accepted_at_us = esp_timer_get_time();
        speaker_activity_.RecordAccepted(
            started_generation, accepted, accepted_at_us);
        if (accepted > 0 && started_generation == speaker_activity_.generation()) {
            PublishAcceptedLocked(data, accepted, volume, accepted_at_us);
        } else if (accepted > 0) {
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
    if (log_short) {
        ESP_LOGW("SenseAEC", "incomplete speaker I2S write: %d/%d frames; %u short writes; A2 integrity FAILED",
                 accepted, samples, static_cast<unsigned>(short_writes));
    }
    return accepted;
}

void SenseReferenceCodec::ClearReference() {
#ifdef CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED
    // The operator's mute, barge-in or playback reset invalidates the
    // calibration trial and securely erases any retained microphone PCM.
    AbortBenchPcmCapture();
#endif
    std::lock_guard<std::mutex> lock(reference_mutex_);
    // Invalidate writes that entered the inherited blocking I2S path before
    // this reset. Never reset this generation with the ring write index.
    speaker_activity_.Reset();
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
        stale_publish_discards_, short_output_writes_,
        microphone_frames_read_, speaker_frames_accepted_,
        microphone_privacy_muted_.load(std::memory_order_acquire),
        microphone_privacy_epoch_.load(std::memory_order_acquire),
        reference_integrity_failed_};
}

void SenseReferenceCodec::EnableOutput(bool enable) {
    if (!enable) {
        // Urgent output disable invalidates reference for canceled audio.
        ClearReference();
    }
    NoAudioCodec::EnableOutput(enable);
}

#ifdef CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED
void SenseReferenceCodec::ReleaseBenchPcmCapture(int16_t* data) {
    if (!data) return;
    // Volatile wipe cannot be optimized away before returning PSRAM to the
    // allocator. The data never survives this private diagnostic session.
    volatile uint8_t* bytes = reinterpret_cast<volatile uint8_t*>(data);
    for (std::size_t i = 0; i < desk_robot::SensePcmWindow::kBytes; ++i)
        bytes[i] = 0;
    heap_caps_free(data);
}

void SenseReferenceCodec::BenchPcmExpiry(void* context) {
    auto* codec = static_cast<SenseReferenceCodec*>(context);
    int16_t* expired = nullptr;
    {
        std::lock_guard<std::mutex> lock(codec->bench_mutex_);
        // Check expiry and transfer ownership in ONE critical section.
        // A delayed old callback must not erase a new capture afterward.
        if (codec->bench_started_us_ == 0 ||
            esp_timer_get_time() - codec->bench_started_us_ < 12'000'000)
            return;
        expired = codec->bench_window_.discard();
        codec->bench_capture_generation_.fetch_add(
            1, std::memory_order_acq_rel);
        codec->bench_started_us_ = 0;
    }
    ReleaseBenchPcmCapture(expired);
}

bool SenseReferenceCodec::BeginBenchPcmCapture() {
    std::lock_guard<std::mutex> lock(bench_mutex_);
    if (bench_window_.occupied() || bench_transfer_active_ ||
        microphone_privacy_muted_.load(std::memory_order_acquire)) return false;
    if (!bench_expiry_timer_) {
        esp_timer_create_args_t args = {};
        args.callback = &SenseReferenceCodec::BenchPcmExpiry;
        args.arg = this;
        args.name = "sense_pcm_bench";
        if (esp_timer_create(&args, &bench_expiry_timer_) != ESP_OK) return false;
    }
    // Private opt-in build only. Never allocate a large audio buffer
    // during normal Xiaozhi operation or fall back to internal DMA RAM.
    auto* data = static_cast<int16_t*>(heap_caps_malloc(
        desk_robot::SensePcmWindow::kBytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (!data) return false;
    // No stale heap data may be delivered if a partial callback occurs.
    std::fill_n(data, desk_robot::SensePcmWindow::kFrames * 2, 0);
    const int64_t now = esp_timer_get_time();
    if (!bench_window_.begin(data, now)) {
        ReleaseBenchPcmCapture(data);
        return false;
    }
    (void)esp_timer_stop(bench_expiry_timer_); // harmless if not active
    if (esp_timer_start_once(bench_expiry_timer_, 12'000'000) != ESP_OK) {
        ReleaseBenchPcmCapture(bench_window_.discard());
        return false;
    }
    bench_started_us_ = now;
    {
        // Lock ordering matches ClearReference: bench, then reference.
        // The snapshot belongs to this authenticated START, not a later
        // asynchronous HTTP read of lifetime counters.
        std::lock_guard<std::mutex> reference_lock(reference_mutex_);
        bench_speaker_at_start_ = speaker_activity_.BeginWindow();
    }
    bench_speaker_activity_in_window_ = false;
    bench_capture_generation_.fetch_add(1, std::memory_order_acq_rel);
    return true;
}

SenseReferenceCodec::BenchCaptureProgress
SenseReferenceCodec::GetBenchPcmProgress() {
    std::lock_guard<std::mutex> lock(bench_mutex_);
    return {
        bench_window_.occupied() && !bench_window_.ready() && !bench_window_.failed(),
        bench_window_.ready(),
        bench_window_.failed(),
        bench_window_.frames_received(),
        bench_capture_generation_.load(std::memory_order_acquire),
        bench_window_.ready() && bench_speaker_activity_in_window_,
    };
}

desk_robot::SensePcmWindow::Complete SenseReferenceCodec::TakeBenchPcmCapture(
    uint64_t expected_generation) {
    std::lock_guard<std::mutex> lock(bench_mutex_);
    if (bench_capture_generation_.load(std::memory_order_acquire) != expected_generation ||
        microphone_privacy_muted_.load(std::memory_order_acquire))
        return {};
    // Transfer ownership to one authenticated HTTP worker. No second
    // capture may allocate PSRAM until this worker releases its old buffer.
    auto completed = bench_window_.take();
    if (completed.interleaved) bench_transfer_active_ = true;
    return completed;
}

void SenseReferenceCodec::EndBenchPcmTransfer() {
    std::lock_guard<std::mutex> lock(bench_mutex_);
    bench_transfer_active_ = false;
}

void SenseReferenceCodec::AbortBenchPcmCapture() {
    int16_t* data = nullptr;
    {
        std::lock_guard<std::mutex> lock(bench_mutex_);
        // Revoke ownership before freeing the in-codec allocation.
        // A moved HTTP buffer stays owned by the worker but its generation
        // fence is invalidated immediately.
        bench_capture_generation_.fetch_add(1, std::memory_order_acq_rel);
        data = bench_window_.discard();
        bench_started_us_ = 0;
    }
    ReleaseBenchPcmCapture(data);
}
#endif
