#include <algorithm>
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
#define ESP_LOGW(...) do {} while(false)
#define ESP_LOGE(...) do {} while(false)
static int i2s_channel_write(int, const void* buf, std::size_t bytes, std::size_t* accepted, int ticks) {
    if (ticks != 120) std::abort();
    ++calls;
    first_sample = static_cast<const int32_t*>(buf)[0];
    *accepted = written ? written : bytes;
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
class AudioCodec {
public:
    AudioCodec();
    virtual ~AudioCodec();
    static constexpr int kSenseTxScratchSamples = 32000;
    int32_t* sense_tx_scratch_ = nullptr;
};
#include "lifecycle.inc"
class NoAudioCodec : public AudioCodec {
public:
    int Write(const int16_t* data, int samples);
    int output_volume_ = 100;
private:
    std::mutex data_if_mutex_;
    int tx_handle_ = 0;
};
#include "writer.inc"
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
}
