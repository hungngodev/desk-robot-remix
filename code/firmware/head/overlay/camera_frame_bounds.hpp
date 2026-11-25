#pragma once

#include <cstddef>

namespace desk_robot {
// Both RGB565 candidates are configured at QVGA or VGA. Reject corrupt
// dimensions before multiplying or reading the DMA frame buffer.
constexpr bool ValidRgb565Frame(std::size_t width, std::size_t height,
                                std::size_t bytes) {
    constexpr std::size_t kMaxPixels = 640 * 480;
    return width > 0 && height > 0 && width <= 640 && height <= 640 &&
           width <= kMaxPixels / height && bytes == width * height * 2;
}
}  // namespace desk_robot
