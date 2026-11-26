/*
 * Playback-reference ring and resampling adapted from RIO aec.cpp,
 * pinned at b911305e48ce6a1b75fe6c07fc02f86ad7bfeb0a.
 * RIO's independent AEC/NS/VAD pipeline is not incorporated here.
 * Upstream license (retained for the adapted portions):
 *
 * MIT License
 *
 * Copyright (c) 2026 Mritunjay Kumar Ray
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */

#include "sense_reference_codec.h"

#include <algorithm>
#include <esp_timer.h>
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
    // Silence represents a break in the accepted PCM stream. Do not replay
    // pre-gap filter history when the next chunk arrives. Keep the 2:1
    // phase: inserting whole reference frames does not change its parity.
    if (sample_gap != 0) {
        reference_decimator_.ClearHistory();
    }
    for (uint64_t n = 0; n < sample_gap; ++n) {
        PushLocked(0);
    }
}

void SenseReferenceCodec::PublishAcceptedLocked(
    const int32_t* source, int samples, int64_t now_us) {
    FillSilenceLocked(now_us);
    // The canonical TX scratch contains the actual converted PCM32 submitted
    // to I2S. Do not recompute volume from a setting that may have changed.
    for (int i = 0; i < samples; ++i) {
        const int16_t scaled = desk_robot::Pcm32ToReferenceSample(source[i]);
        // Filter the actual accepted PCM before reducing its sample rate.
        // One output at most per input, with history and pair phase retained.
        int16_t filtered = 0;
        if (reference_decimator_.Push(scaled, filtered)) {
            PushLocked(filtered);
        }
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
    // Check every completed microphone read, even when its requested
    // reference window is unavailable. Otherwise an underflow can hide a
    // full lap until a later valid read (or forever if underflow persists).
    const bool lapped = reference_read_seen_ &&
        write_index_ - last_reference_read_write_index_ >= kRingSize;
    last_reference_read_write_index_ = write_index_;
    reference_read_seen_ = true;
    if (lapped) {
        if (reference_overwrite_reads_ != UINT32_MAX) ++reference_overwrite_reads_;
        reference_integrity_failed_ = true;
    }
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
    if (lapped) {
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
    if (microphone_privacy_muted_.load(std::memory_order_acquire)) {
        std::fill_n(dest, samples, 0);
        return 0;
    }
    // The head owns one realtime capture reader. A bounded mutex also
    // prevents concurrent callbacks from corrupting shared frame scratch.
    std::lock_guard<std::mutex> input_lock(input_read_mutex_);
    // Consent may have changed while this callback waited for the reader
    // mutex. Do not start a new hardware read on a revoked capture epoch.
    if (microphone_privacy_muted_.load(std::memory_order_acquire) ||
        privacy_epoch != microphone_privacy_epoch_.load(std::memory_order_acquire)) {
        std::fill_n(dest, samples, 0);
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
            if (bench_window_.failed()) {
                std::lock_guard<std::mutex> reference_lock(reference_mutex_);
                speaker_activity_.EndWindow(bench_speaker_at_start_);
            }
        }
#endif
        // Count actual driver failures in every build, not just private AEC
        // captures. A short read is not proof of a hardware DMA queue overflow.
        {
            std::lock_guard<std::mutex> diagnostics_lock(reference_mutex_);
            if (short_input_reads_ != UINT32_MAX) ++short_input_reads_;
            reference_integrity_failed_ = true;
        }
        // An error or short PDM read can still have written raw microphone PCM.
        std::fill_n(microphone_frame_.begin(), frames, 0);
        std::fill_n(dest, samples, 0);
        return 0; // AudioCodec::InputData is boolean; reject partial frames.
    }
    // Discard a PDM read that crossed a physical BOOT mute/unmute epoch.
    if (microphone_privacy_muted_.load(std::memory_order_acquire) ||
        privacy_epoch != microphone_privacy_epoch_.load(std::memory_order_acquire)) {
        std::fill_n(microphone_frame_.begin(), frames, 0);
        std::fill_n(dest, samples, 0);
        return 0;
    }
    // Timestamp the completed PDM read once, before reference work or task
    // scheduling can add an unrelated delay. This is a source-clock estimate,
    // not a hardware exposure or acoustic speaker-playback receipt.
    const int64_t capture_end_us = esp_timer_get_time();
    bool reference_ready = false;
    {
        std::lock_guard<std::mutex> lock(reference_mutex_);
        // Only successful, complete microphone reads advance actual input
        // activity. Counting attempted reads would fake an active PDM stream.
        microphone_frames_read_ += std::min(
            static_cast<uint32_t>(frames), UINT32_MAX - microphone_frames_read_);
        FillSilenceLocked(capture_end_us);
        reference_ready = ReadReferenceLocked(
            reference_frame_.data(), frames, capture_end_us);
    }
    // Integrity counters are exposed by GetReferenceDiagnostics(). Never
    // synchronously log on the microphone task, even outside the ring lock.
    for (int i = 0; i < frames; ++i) {
        dest[2 * i] = microphone_frame_[i];
        dest[2 * i + 1] = reference_frame_[i];
    }
    // Check again after mixing AEC channels, before any raw PCM capture.
    if (microphone_privacy_muted_.load(std::memory_order_acquire) ||
        privacy_epoch != microphone_privacy_epoch_.load(std::memory_order_acquire)) {
        std::fill_n(dest, samples, 0);
        std::fill_n(microphone_frame_.begin(), frames, 0);
        std::fill_n(reference_frame_.begin(), frames, 0);
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
                speaker_activity_.EndWindow(bench_speaker_at_start_);
            } else if (bench_window_.failed()) {
                std::lock_guard<std::mutex> reference_lock(reference_mutex_);
                speaker_activity_.EndWindow(bench_speaker_at_start_);
            }
        }
    }
#endif
    // The live output and optional consented bench window now own their copies.
    // Do not retain PCM in reusable scratch between reads, including during mute.
    std::fill_n(microphone_frame_.begin(), frames, 0);
    std::fill_n(reference_frame_.begin(), frames, 0);
    // BOOT may arrive during a bounded private capture copy. The mute
    // setter invalidates the buffer and these samples never reach Opus.
    if (microphone_privacy_muted_.load(std::memory_order_acquire) ||
        privacy_epoch != microphone_privacy_epoch_.load(std::memory_order_acquire)) {
        std::fill_n(dest, samples, 0);
        return 0;
    }
    return samples;
}

int SenseReferenceCodec::Write(const int16_t* data, int samples) {
    if (data == nullptr || samples <= 0 || samples > static_cast<int>(kSpeakerRate) ||
        output_sample_rate_ != static_cast<int>(kSpeakerRate)) {
        return 0;
    }
    uint64_t started_generation = 0;
    {
        std::lock_guard<std::mutex> lock(reference_mutex_);
        started_generation = speaker_activity_.generation();
    }
    // Retain the exact TX scratch until reference publication; the base
    // data_if_mutex_ alone ends before this wrapper can consume its PCM.
    std::lock_guard<std::mutex> output_lock(output_write_mutex_);
    {
        std::lock_guard<std::mutex> lock(reference_mutex_);
        if (started_generation != speaker_activity_.generation()) return 0;
    }
    // The selected Sense overlay already bounds the pinned Xiaozhi writer's
    // I2S wait. Preserve its mutex, squared-volume PCM conversion and sole
    // speaker owner rather than maintaining a second codec implementation.
    const int accepted = NoAudioCodec::Write(data, samples);
    // Timestamp the I2S return before waiting for reference publication.
    // Lock contention must not move an old digital accept into a new MIC window.
    const int64_t accepted_at_us = esp_timer_get_time();
    bool stale_write = false;
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
            reference_integrity_failed_ = true;
        }
        speaker_activity_.RecordAccepted(
            started_generation, accepted, accepted_at_us);
        if (accepted > 0 && started_generation == speaker_activity_.generation()) {
            PublishAcceptedLocked(sense_tx_scratch_, accepted, accepted_at_us);
        } else if (accepted > 0) {
            // The physical TX DMA may have accepted some old audio. It must
            // NOT be relabeled as current-generation echo reference.
            stale_write = true;
            if (stale_publish_discards_ != UINT32_MAX) ++stale_publish_discards_;
            reference_integrity_failed_ = true;
        }
    }
    // The authenticated diagnostic reader observes these sticky counters;
    // serial console backpressure must not delay the speaker task.
    // An obsolete write cannot extend the current media receipt prefix.
    return stale_write ? 0 : accepted;
}

void SenseReferenceCodec::ClearReference() {
#ifdef CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED
    // The operator's mute, barge-in or playback reset invalidates the
    // calibration trial and securely erases any retained microphone PCM.
    AbortBenchPcmCapture(false);  // Playback reset invalidates PCM, not an unused grant.
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
    reference_decimator_.Reset();
}

SenseReferenceCodec::ReferenceDiagnostics
SenseReferenceCodec::GetReferenceDiagnostics() {
    std::lock_guard<std::mutex> lock(reference_mutex_);
    return ReferenceDiagnostics{
        missing_reference_reads_, reference_overwrite_reads_,
        stale_publish_discards_, short_output_writes_, short_input_reads_,
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
    // This controls the inherited digital I2S output only. No SD_MODE GPIO
    // or amplifier supply switch is wired in this profile. It cannot prove
    // acoustic silence, pop-free shutdown, or removal of amplifier power.
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
        {
            std::lock_guard<std::mutex> reference_lock(codec->reference_mutex_);
            codec->speaker_activity_.EndWindow(codec->bench_speaker_at_start_);
        }
        codec->bench_capture_generation_.fetch_add(
            1, std::memory_order_acq_rel);
        codec->bench_started_us_ = 0;
    }
    ReleaseBenchPcmCapture(expired);
}

void SenseReferenceCodec::GrantBenchPcmConsent() {
    std::lock_guard<std::mutex> lock(bench_mutex_);
    if (!microphone_privacy_muted_.load(std::memory_order_acquire))
        bench_consent_.Grant(esp_timer_get_time());
}

bool SenseReferenceCodec::BeginBenchPcmCapture(uint32_t expected_privacy_epoch) {
    std::lock_guard<std::mutex> lock(bench_mutex_);
    const auto privacy_changed = [&] {
        return microphone_privacy_muted_.load(std::memory_order_acquire) ||
            microphone_privacy_epoch_.load(std::memory_order_acquire) != expected_privacy_epoch;
    };
    if (bench_window_.occupied() || bench_transfer_active_ || privacy_changed()) return false;
    // Consume before allocation or timer setup: failed START must not
    // authorize a second network request without another physical gesture.
    if (!bench_consent_.Take(esp_timer_get_time())) return false;
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
    if (privacy_changed()) {
        ReleaseBenchPcmCapture(data);
        return false;
    }
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
    if (privacy_changed()) {
        (void)esp_timer_stop(bench_expiry_timer_);
        bench_started_us_ = 0;
        {
            std::lock_guard<std::mutex> reference_lock(reference_mutex_);
            speaker_activity_.EndWindow(bench_speaker_at_start_);
        }
        ReleaseBenchPcmCapture(bench_window_.discard());
        return false;
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

void SenseReferenceCodec::AbortBenchPcmCapture(bool revoke_consent) {
    int16_t* data = nullptr;
    {
        std::lock_guard<std::mutex> lock(bench_mutex_);
        if (revoke_consent) bench_consent_.Revoke();
        // Revoke ownership before freeing the in-codec allocation.
        // A moved HTTP buffer stays owned by the worker but its generation
        // fence is invalidated immediately.
        bench_capture_generation_.fetch_add(1, std::memory_order_acq_rel);
        data = bench_window_.discard();
        {
            std::lock_guard<std::mutex> reference_lock(reference_mutex_);
            speaker_activity_.EndWindow(bench_speaker_at_start_);
        }
        bench_started_us_ = 0;
    }
    ReleaseBenchPcmCapture(data);
}
#endif
