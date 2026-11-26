#pragma once

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
constexpr int PupilX(int offset) { return (kEyeWidth - kPupilWidth) / 2 + offset; }
constexpr int PupilY(int height, int offset) {
    return (height - kPupilHeight) / 2 + (height == kOpenHeight ? offset : 0);
}
}  // namespace desk_robot::face_eye_geometry
