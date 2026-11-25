#include <algorithm>
#include <array>
#include <atomic>
#include "reference_decimator.h"
#include "reference_timeline.h"
#include "sense_speaker_activity.hpp"
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <mutex>
#include <new>
#include <vector>

static unsigned allocations = 0;
void* operator new(std::size_t n) {
    ++allocations;
    if (void* p = std::malloc(n)) return p;
    throw std::bad_alloc();
}
void operator delete(void* p) noexcept { std::free(p); }
void operator delete(void* p, std::size_t) noexcept { std::free(p); }
static std::size_t written = 0;
static int err = 0;
static unsigned calls = 0;
static int32_t first_sample = 0;
using esp_err_t = int;
constexpr int ESP_OK = 0;
#define CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3 1
#define pdMS_TO_TICKS(x) (x)
template<class... Args> void ignored_log(Args&&...) {}
#define ESP_LOGW(...) ignored_log(__VA_ARGS__)
#define ESP_LOGE(...) ignored_log(__VA_ARGS__)
#define ESP_LOGI(...) ignored_log(__VA_ARGS__)
static constexpr const char* TAG = "native";
static void change_volume_during_write();
static void change_volume_before_conversion();
static int64_t esp_timer_get_time() { return 1000000; }
static int i2s_channel_write(int, const void* buf, std::size_t bytes, std::size_t* accepted, int ticks) {
    if (ticks != 120) std::abort();
    ++calls;
    first_sample = static_cast<const int32_t*>(buf)[0];
    *accepted = written ? written : bytes;
    change_volume_during_write();
    return err;
}
static unsigned startup_allocations = 0;
static unsigned startup_releases = 0;
static bool refuse_memory = false;
constexpr unsigned MALLOC_CAP_SPIRAM = 1;
constexpr unsigned MALLOC_CAP_8BIT = 2;
static int32_t scratch[32000];
static void* heap_caps_malloc(std::size_t size, unsigned caps) {
    if (size != sizeof(scratch) || caps != (MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT))
        std::abort();
    ++startup_allocations;
    return refuse_memory ? nullptr : scratch;
}
static void heap_caps_free(void* p) {
    if (p != scratch) std::abort();
    ++startup_releases;
}
class Settings {
public:
    Settings(const char*, bool) {}
    void SetInt(const char*, int) {}
};
class AudioCodec {
public:
    AudioCodec();
    virtual ~AudioCodec();
    std::atomic<int> output_volume_{100};
    int output_volume() const { return output_volume_; }
    void SetOutputVolume(int volume);
    static constexpr int kSenseTxScratchSamples = 32000;
    int32_t* sense_tx_scratch_ = nullptr;
};
#include "lifecycle.inc"
#include "volume.inc"
static AudioCodec* change_volume = nullptr;
static bool change_before = false;
static void change_volume_before_conversion() {
    if (change_volume && change_before) change_volume->SetOutputVolume(10);
}
static void change_volume_during_write() {
    if (change_volume && !change_before) change_volume->SetOutputVolume(10);
}
class NoAudioCodec : public AudioCodec {
public:
    int Write(const int16_t* data, int samples);
private:
    std::mutex data_if_mutex_;
    int tx_handle_ = 0;
};
#include "writer.inc"
class SenseReferenceCodec : public NoAudioCodec {
public:
    int Write(const int16_t* data, int samples);
    void PublishAcceptedLocked(const int32_t* source, int samples, int64_t now_us);
    static constexpr int kSpeakerRate = 32000, kMicRate = 16000;
    int output_sample_rate_ = kSpeakerRate;
    std::mutex output_write_mutex_, reference_mutex_;
    desk_robot::SenseSpeakerActivity speaker_activity_;
    desk_robot::PlaybackReferenceClock reference_clock_;
    uint32_t speaker_frames_accepted_ = 0, short_output_writes_ = 0;
    uint32_t stale_publish_discards_ = 0;
    bool reference_integrity_failed_ = false;
    desk_robot::ReferenceDecimator reference_decimator_{};
    std::array<int16_t, 16384> ring{};
    size_t n = 0;
    void FillSilenceLocked(int64_t now_us) { reference_clock_.silence_frames(now_us, 0); }
    void PushLocked(int16_t sample) { ring.at(n++) = sample; }
};
#include "sense_writer.inc"
#include "publish.inc"
#define CHECK(x) do { if (!(x)) { std::cerr << "FAIL " << #x << '\n'; return 1; } } while(false)
int main() {
    static int16_t pcm[NoAudioCodec::kSenseTxScratchSamples];
    pcm[0] = -32768;
    {
        NoAudioCodec codec;
        CHECK(startup_allocations == 1);
        CHECK(codec.sense_tx_scratch_ == scratch);
        const auto before = allocations;
        for (int i=0; i<1000; ++i) CHECK(codec.Write(pcm, 1920) == 1920);
        const auto delta = allocations-before;
        std::cout << "allocations during 1000 TX callbacks: " << delta << '\n';
        CHECK(delta == 0);
        CHECK(first_sample == INT32_MIN);
        CHECK(codec.Write(pcm, 32000) == 32000);
        written = 4; CHECK(codec.Write(pcm, 1920) == 1);
        written = 3; CHECK(codec.Write(pcm, 1920) == 0);
        written = 1921 * 4; CHECK(codec.Write(pcm, 1920) == 0);
        err = 1; written = 4; CHECK(codec.Write(pcm, 1920) == 0);
        const auto old_calls = calls;
        CHECK(codec.Write(nullptr, 1920) == 0);
        CHECK(codec.Write(pcm, -1) == 0);
        CHECK(codec.Write(pcm, 32001) == 0);
        CHECK(calls == old_calls);
        CHECK(startup_allocations == 1);
    }
    CHECK(startup_releases == 1);
    refuse_memory = true;
    {
        NoAudioCodec unavailable;
        const auto old_calls = calls;
        CHECK(unavailable.Write(pcm, 1920) == 0);
        CHECK(calls == old_calls);
    }
    CHECK(startup_allocations == 2);
    CHECK(startup_releases == 1);
    std::cout << "PASS allocation-free TX, bounds, short/error writes\n";
    refuse_memory = false;
    written = 0;
    err = 0;
    SenseReferenceCodec sense;
    std::fill_n(pcm, 64, -32768);
    change_volume = &sense;
    CHECK(sense.Write(pcm, 64) == 64);
    CHECK(first_sample == INT32_MIN);
    CHECK(sense.output_volume() == 10);
    CHECK(sense.n == 32);
    CHECK(sense.ring[31] == -32768);
    change_volume = nullptr;
    CHECK(sense.Write(pcm, 64) == 64);
    CHECK(sense.n == 64);
    CHECK(sense.ring[63] == -328);
    sense.SetOutputVolume(100);
    change_volume = &sense;
    change_before = true;
    CHECK(sense.Write(pcm, 64) == 64);
    CHECK(sense.n == 96);
    CHECK(sense.ring[95] == -328);
    CHECK(!sense.reference_integrity_failed_);
    std::cout << "PASS actual accepted PCM gain across mid-write volume change\n";
}
