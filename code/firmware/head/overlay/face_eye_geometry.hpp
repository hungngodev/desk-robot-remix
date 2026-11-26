#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>

namespace desk_robot::face_eye_geometry {
// Existing 128x64 Xiaozhi OLED idle emotion slot, in pixels. Keep these
// dimensions out of the semantic StackChan HSM and share them with animation.
inline constexpr int kPanelWidth = 128;
inline constexpr int kPanelHeight = 64;
inline constexpr int kStatusHeight = 16;
inline constexpr int kSlotWidth = 32;
inline constexpr int kSlotHeight = kPanelHeight - kStatusHeight;
inline constexpr int kEyeCount = 2;
inline constexpr int kEyeWidth = 11;
inline constexpr int kOpenHeight = 14;
inline constexpr int kClosedHeight = 2;
inline constexpr int kEyeLeft = 3;
inline constexpr int kEyeStride = 15;
inline constexpr int kPupilWidth = 3;
inline constexpr int kPupilHeight = 4;
inline constexpr int kPupilMinEyeHeight = 6;
inline constexpr int8_t kGazeExtent = 3;
inline constexpr int8_t kNodReturn = -2;

constexpr int EyeX(int index) { return kEyeLeft + index * kEyeStride; }
constexpr int EyeY(int height) { return kSlotHeight / 2 - height / 2; }
// Nonfinite observations have no direction. Saturate finite coordinates before
// scaling or converting to an integer; keep rounding symmetric about center.
inline int8_t NormalizedGazeOffset(float coordinate) noexcept {
    if (!std::isfinite(coordinate)) return 0;
    return static_cast<int8_t>(std::lround(std::clamp(coordinate, -1.0f, 1.0f) * kGazeExtent));
}

constexpr int ClampGazeOffset(int offset) {
    return std::clamp(offset, -static_cast<int>(kGazeExtent), static_cast<int>(kGazeExtent));
}
constexpr int PupilX(int offset) {
    return (kEyeWidth - kPupilWidth) / 2 + ClampGazeOffset(offset);
}
constexpr int PupilY(int height, int offset) {
    // Preserve gaze as the lid opens/closes, within the space the pupil has.
    const int space = std::max(0, std::clamp(height, kClosedHeight, kOpenHeight) - kPupilHeight);
    const int center = space / 2;
    const int extent = std::min(center, static_cast<int>(kGazeExtent));
    return center + std::clamp(offset, -extent, extent);
}
}  // namespace desk_robot::face_eye_geometry
