#pragma once

namespace desk_robot {
enum class FaceStatus {
    kNormal, kBodyFault, kDockLock, kMicPrivacy, kFaceUnavailable, kVoiceLinkLost
};

constexpr FaceStatus SelectFaceStatus(bool body_fault, bool dock_lockout, bool mic_privacy,
                                      bool voice_link_lost = false) {
    if (body_fault) return dock_lockout ? FaceStatus::kDockLock : FaceStatus::kBodyFault;
    if (mic_privacy) return FaceStatus::kMicPrivacy;
    return voice_link_lost ? FaceStatus::kVoiceLinkLost : FaceStatus::kNormal;
}

// A lost voice link is information, not a body fault or a privacy command.
// Preserve locally generated eyes while its factual status remains visible.
constexpr bool FaceStatusBlocksExpression(FaceStatus status) {
    return status != FaceStatus::kNormal && status != FaceStatus::kVoiceLinkLost;
}
}  // namespace desk_robot
