#include "sense_reference_codec.h"

#include <algorithm>
#include <cmath>
#include <esp_timer.h>

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
    if (last_write_us_ <= 0) {
        last_write_us_ = now_us;
        return;
    }
    if (now_us <= last_write_us_ + 20000) {
        return;
    }
    // Reuse RIO's essential idea: a silent interval advances the reference.
    // Otherwise the first word of a new turn would subtract the previous
    // turn's old audio as though it had just played.
    uint64_t sample_gap = static_cast<uint64_t>(now_us - last_write_us_ - 20000)
                          * kMicRate / 1000000;
    sample_gap = std::min<uint64_t>(sample_gap, kMaxGapSamples);
    for (uint64_t n = 0; n < sample_gap; ++n) {
        PushLocked(0);
    }
    last_write_us_ = now_us;
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
        // RIO's streaming three tap low pass then 3:2 decimation. Preserve
        // filter and fractional phase across decoder chunk boundaries.
        const int32_t filtered = (static_cast<int32_t>(filter_last2_) +
                                  2 * static_cast<int32_t>(filter_last1_) +
                                  scaled) / 4;
        filter_last2_ = filter_last1_;
        filter_last1_ = static_cast<int16_t>(scaled);
        while (phase_ < 1.0f) {
            const int32_t result = static_cast<int32_t>(
                last_filtered_ + (filtered - last_filtered_) * phase_);
            PushLocked(static_cast<int16_t>(std::clamp(result, -32768, 32767)));
            phase_ += 1.5f;
        }
        phase_ -= 1.0f;
        last_filtered_ = static_cast<int16_t>(filtered);
    }
    last_write_us_ = now_us;
}

void SenseReferenceCodec::ReadReferenceLocked(int16_t* dest, int frames) {
    if (write_index_ < kDelaySamples + static_cast<uint32_t>(frames)) {
        std::fill_n(dest, frames, 0);
        return;
    }
    const uint64_t start = write_index_ - kDelaySamples - frames;
    for (int i = 0; i < frames; ++i) {
        dest[i] = reference_[(start + i) & (kRingSize - 1)];
    }
}

int SenseReferenceCodec::Read(int16_t* dest, int samples) {
    if (dest == nullptr || samples <= 0 || samples % 2 ||
        samples > 4096 || input_sample_rate_ != static_cast<int>(kMicRate)) {
        return 0;
    }
    const int frames = samples / 2;
    std::vector<int16_t> microphone(frames);
    std::vector<int16_t> reference(frames);
    // Keep microphone/I2S read outside reference_mutex_: it can block for
    // samples and must never prevent the output task publishing a reference.
    const int mic_read = NoAudioCodecSimplexPdm::Read(microphone.data(), frames);
    if (mic_read != frames) {
        return 0; // AudioCodec::InputData is boolean; reject partial frames.
    }
    {
        std::lock_guard<std::mutex> lock(reference_mutex_);
        FillSilenceLocked(esp_timer_get_time());
        ReadReferenceLocked(reference.data(), frames);
    }
    for (int i = 0; i < frames; ++i) {
        dest[2 * i] = microphone[i];
        dest[2 * i + 1] = reference[i];
    }
    return samples;
}

int SenseReferenceCodec::Write(const int16_t* data, int samples) {
    if (data == nullptr || samples <= 0 || samples > 24000 ||
        output_sample_rate_ != static_cast<int>(kSpeakerRate)) {
        return 0;
    }
    const int volume = output_volume_;
    // Reuse the already working Xiaozhi 32-bit I2S driver, including partial
    // write accounting, not a second amplifier writer or competing driver.
    const int accepted = NoAudioCodec::Write(data, samples);
    if (accepted > 0) {
        std::lock_guard<std::mutex> lock(reference_mutex_);
        PublishAcceptedLocked(data, accepted, volume, esp_timer_get_time());
    }
    return accepted;
}

void SenseReferenceCodec::ClearReference() {
    std::lock_guard<std::mutex> lock(reference_mutex_);
    reference_.fill(0);
    write_index_ = 0;
    last_write_us_ = 0;
    filter_last1_ = 0;
    filter_last2_ = 0;
    last_filtered_ = 0;
    phase_ = 0.0f;
}
