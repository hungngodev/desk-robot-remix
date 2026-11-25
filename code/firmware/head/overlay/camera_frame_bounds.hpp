#pragma once

#include <cstddef>

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
}  // namespace desk_robot
