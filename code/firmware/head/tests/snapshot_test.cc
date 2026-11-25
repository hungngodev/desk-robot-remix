// Exercise the actual snapshot adapter with fake capture/encoding boundaries.
// Sensor acquisition and image encoding still require the real device.
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <expected>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

enum { PIXFORMAT_RGB565, PIXFORMAT_JPEG, PIXFORMAT_OTHER, V4L2_PIX_FMT_RGB565 };
struct Frame {
    uint8_t* buf;
    size_t len;
    uint16_t width;
    uint16_t height;
    int format;
};
using camera_fb_t = Frame;
int returned_frames = 0;
std::recursive_mutex* shared_camera_mutex = nullptr;

// A recursive mutex can be acquired again by its owner, so probing it on
// the capture thread would conceal an accidentally retained lock.
bool CameraLockAvailable() {
    bool available = false;
    std::thread other([&] {
        available = shared_camera_mutex->try_lock();
        if (available) shared_camera_mutex->unlock();
    });
    other.join();
    return available;
}
void esp_camera_fb_return(camera_fb_t* frame) {
    assert(frame != nullptr);
    assert(!CameraLockAvailable());
    ++returned_frames;
}
bool encoder_ok = true;
bool encoder_framing_ok = true;
bool image_to_jpeg(uint8_t* src, size_t size, uint16_t width, uint16_t height,
                   int format, int quality, uint8_t** out, size_t* len) {
    assert(!CameraLockAvailable());
    assert(size == 8 && width == 2 && height == 2);
    assert(format == V4L2_PIX_FMT_RGB565 && quality == 80);
    if (!encoder_ok) return false;
    *len = 5;
    *out = static_cast<uint8_t*>(malloc(*len));
    const uint8_t bytes[] = {0xff, 0xd8, src[0], 0xff, static_cast<uint8_t>(encoder_framing_ok ? 0xd9 : 0)};
    std::copy(bytes, bytes + 5, *out);
    return true;
}
class Esp32Camera {
public:
    int capture_calls = 0;
    bool capture_ok = true;
    bool frame_available = true;
    bool native_jpeg_ok = true;
    uint8_t pixels[8] = {};
    Frame frame{pixels, 8, 2, 2, PIXFORMAT_RGB565};
    Frame* current_fb_ = nullptr;
    uint8_t* encode_buf_ = pixels;
    std::recursive_mutex mutex;
    std::recursive_mutex& AccessMutex() { return mutex; }
    bool Capture() {
        std::lock_guard<std::recursive_mutex> lock(AccessMutex());
        ++capture_calls;
        if (current_fb_) esp_camera_fb_return(current_fb_);
        current_fb_ = frame_available ? &frame : nullptr;
        if (!current_fb_) return false;
        if (frame.format == PIXFORMAT_JPEG) {
            // A native camera frame must actually begin with SOI and end
            // with EOI. The prior synthetic JPEG was four arbitrary RGB
            // bytes and rightly failed the new production validation.
            pixels[0] = 0xff;
            pixels[1] = 0xd8;
            pixels[2] = 0xff;
            pixels[3] = native_jpeg_ok ? 0xd9 : 0;
        } else {
            pixels[0] = static_cast<uint8_t>(capture_calls);
        }
        return capture_ok;
    }
    std::expected<std::vector<uint8_t>, std::string> SnapshotJpeg();
};
#include "modular_snapshot.inc"

int main() {
    Esp32Camera camera;
    shared_camera_mutex = &camera.AccessMutex();
    const auto capture = [&camera]() {
        const int before = returned_frames;
        const bool available = camera.frame_available;
        auto result = camera.SnapshotJpeg();
        assert(CameraLockAvailable());
        assert(camera.current_fb_ == nullptr);
        assert(returned_frames == before + (available ? 1 : 0));
        return result;
    };
    auto first = capture();
    auto second = capture();
    assert(first && second && camera.capture_calls == 2);
    assert((*first)[2] == 1 && (*second)[2] == 2);
    camera.capture_ok = false;
    auto failed = capture();
    assert(!failed && failed.error() == "Fresh camera capture failed");
    camera.capture_ok = true;
    encoder_ok = false;
    assert(!capture());
    encoder_ok = true;
    encoder_framing_ok = false;
    assert(!capture());
    encoder_framing_ok = true;
    assert(capture());
    camera.frame.format = PIXFORMAT_OTHER;
    assert(!capture());
    camera.frame.format = PIXFORMAT_JPEG;
    camera.frame.buf = nullptr;
    assert(!capture());
    camera.frame.buf = camera.pixels;
    camera.frame.len = 0;
    assert(!capture());
    camera.frame.len = 3;
    assert(!capture());
    camera.frame.len = 512 * 1024 + 1;
    assert(!capture());
    camera.frame.len = 4;
    assert(capture()->size() == 4);
    camera.native_jpeg_ok = false;
    assert(!capture());
    camera.frame_available = false;
    assert(!capture());
}
