#pragma once

#include <cstddef>
#include <cstdint>

namespace desk_robot {
// Both RGB565 candidates are configured at QVGA or VGA. This is a buffer
// envelope, not an aspect ratio check: allow either orientation and any
// smaller rectangle within the VGA pixel budget. Validate before multiplying
// dimensions or reading the DMA frame buffer.
constexpr bool ValidRgb565Frame(std::size_t width, std::size_t height,
                                std::size_t bytes) {
    constexpr std::size_t kMaxEdge = 640;
    constexpr std::size_t kMaxPixels = kMaxEdge * 480;
    constexpr std::size_t kBytesPerPixel = 2;
    return width > 0 && height > 0 && width <= kMaxEdge && height <= kMaxEdge &&
           width <= kMaxPixels / height &&
           bytes == width * height * kBytesPerPixel;
}

// Envelope check only, not a JPEG decoder. Reject a repeated leading SOI,
// but do not scan opaque APP payloads for marker-like bytes.
constexpr bool ValidJpegFrame(const std::uint8_t* buf, std::size_t len) {
    return buf && len >= 4 && len <= 512 * 1024 &&
           buf[0] == 0xff && buf[1] == 0xd8 &&
           buf[len - 2] == 0xff && buf[len - 1] == 0xd9 &&
           !(buf[2] == 0xff && buf[3] == 0xd8);
}
}  // namespace desk_robot
