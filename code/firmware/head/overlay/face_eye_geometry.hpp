#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>

namespace desk_robot {
namespace face_eye_geometry {
// Existing 128x64 Xiaozhi OLED idle emotion slot, in pixels. Keep these
// dimensions out of the semantic StackChan HSM and share them with animation.
// Preserve the single shared C++17 constant objects used by the renderer;
// C++11 consumers use the same values with internal linkage.
#if __cplusplus >= 201703L
#define DESK_ROBOT_FACE_GEOMETRY_INLINE inline
#else
#define DESK_ROBOT_FACE_GEOMETRY_INLINE
#endif
DESK_ROBOT_FACE_GEOMETRY_INLINE constexpr int kPanelWidth = 128;
DESK_ROBOT_FACE_GEOMETRY_INLINE constexpr int kPanelHeight = 64;
DESK_ROBOT_FACE_GEOMETRY_INLINE constexpr int kStatusHeight = 16;
DESK_ROBOT_FACE_GEOMETRY_INLINE constexpr int kSlotWidth = 32;
DESK_ROBOT_FACE_GEOMETRY_INLINE constexpr int kSlotHeight = kPanelHeight - kStatusHeight;
DESK_ROBOT_FACE_GEOMETRY_INLINE constexpr int kEyeCount = 2;
DESK_ROBOT_FACE_GEOMETRY_INLINE constexpr int kEyeWidth = 11;
DESK_ROBOT_FACE_GEOMETRY_INLINE constexpr int kOpenHeight = 14;
DESK_ROBOT_FACE_GEOMETRY_INLINE constexpr int kClosedHeight = 2;
DESK_ROBOT_FACE_GEOMETRY_INLINE constexpr int kEyeLeft = 3;
DESK_ROBOT_FACE_GEOMETRY_INLINE constexpr int kEyeStride = 15;
DESK_ROBOT_FACE_GEOMETRY_INLINE constexpr int kPupilWidth = 3;
DESK_ROBOT_FACE_GEOMETRY_INLINE constexpr int kPupilHeight = 4;
DESK_ROBOT_FACE_GEOMETRY_INLINE constexpr int kPupilMinEyeHeight = 6;
DESK_ROBOT_FACE_GEOMETRY_INLINE constexpr int8_t kGazeExtent = 3;
DESK_ROBOT_FACE_GEOMETRY_INLINE constexpr int8_t kNodReturn = -2;
#undef DESK_ROBOT_FACE_GEOMETRY_INLINE

namespace detail {
// By-value clamp keeps the geometry constexpr in C++11 and avoids dangling
// references to temporary bounds.
template <typename T>
constexpr T Clamp(T value, T low, T high) {
    return value < low ? low : (value > high ? high : value);
}
}  // namespace detail

// Clamp before arithmetic, including callers outside the current renderer.
constexpr int EyeX(int index) {
    return kEyeLeft + detail::Clamp(index, 0, kEyeCount - 1) * kEyeStride;
}
constexpr int EyeY(int height) {
    return kSlotHeight / 2 - detail::Clamp(height, kClosedHeight, kOpenHeight) / 2;
}
// Nonfinite observations have no direction. Saturate finite coordinates before
// scaling or converting to an integer; keep rounding symmetric about center.
inline int8_t NormalizedGazeOffset(float coordinate) noexcept {
    if (!std::isfinite(coordinate)) return 0;
    return static_cast<int8_t>(std::lround(detail::Clamp(coordinate, -1.0f, 1.0f) * kGazeExtent));
}

constexpr int ClampGazeOffset(int offset) {
    return detail::Clamp(offset, -static_cast<int>(kGazeExtent), static_cast<int>(kGazeExtent));
}
constexpr int PupilX(int offset) {
    return (kEyeWidth - kPupilWidth) / 2 + ClampGazeOffset(offset);
}
namespace detail {
constexpr int PupilCenter(int height) {
    return (Clamp(height, kPupilHeight, kOpenHeight) - kPupilHeight) / 2;
}
}  // namespace detail
constexpr int PupilY(int height, int offset) {
    // Clamp before subtraction. A lid shorter than the pupil has zero travel.
    return detail::PupilCenter(height) + detail::Clamp(
        ClampGazeOffset(offset), -detail::PupilCenter(height), detail::PupilCenter(height));
}
}  // namespace face_eye_geometry
}  // namespace desk_robot
