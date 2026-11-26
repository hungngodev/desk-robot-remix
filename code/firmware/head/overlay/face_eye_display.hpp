#pragma once

#include <algorithm>
#include <optional>
#include <cstring>
#include <string>

#include "display/oled_display.h"
#include "face_eye_animator.hpp"
#include "face_idle_power.hpp"
#include "face_presence.hpp"

// Short eye gestures cover only Xiaozhi's 32-pixel emotion slot.
// All display mutations share Xiaozhi's LVGL lock. Local safety/privacy status
// owns the status label until cleared; upstream still owns audio and subtitles.
// No actuator API is reachable.
namespace desk_robot {

class LocalEyeDisplay final : public OledDisplay {
public:
    using OledDisplay::OledDisplay;

    void SetupUI() override {
        using namespace face_eye_geometry;
        OledDisplay::SetupUI();
        DisplayLockGuard lock(this);
        if (!lock) return;
        if (local_status_ != FaceStatus::kNormal) {
            RememberNormalStatusLocked();
            ApplyPriorityLocked();
        }
        if (eye_layer_ || width() != kPanelWidth || height() != kPanelHeight) return;
        eye_layer_ = lv_obj_create(lv_screen_active());
        lv_obj_set_size(eye_layer_, kSlotWidth, kSlotHeight);
        // Xiaozhi's 128x64 idle emotion cell is 32px wide, centered in
        // the content row. Cover that cell without obscuring its top 16px
        // network/voice status bar or allocating another display surface.
        lv_obj_align(eye_layer_, LV_ALIGN_TOP_MID, 0, kStatusHeight);
        lv_obj_set_style_radius(eye_layer_, 0, 0);
        lv_obj_set_style_pad_all(eye_layer_, 0, 0);
        lv_obj_set_style_border_width(eye_layer_, 0, 0);
        lv_obj_set_style_bg_color(eye_layer_, lv_color_white(), 0);
        lv_obj_set_style_bg_opa(eye_layer_, LV_OPA_COVER, 0);
        lv_obj_set_scrollbar_mode(eye_layer_, LV_SCROLLBAR_MODE_OFF);
        for (int i = 0; i < kEyeCount; ++i) {
            eye_[i] = lv_obj_create(eye_layer_);
            lv_obj_set_size(eye_[i], kEyeWidth, kOpenHeight);
            lv_obj_set_pos(eye_[i], EyeX(i), EyeY(kOpenHeight));
            lv_obj_set_style_radius(eye_[i], LV_RADIUS_CIRCLE, 0);
            lv_obj_set_style_pad_all(eye_[i], 0, 0);
            lv_obj_set_style_border_width(eye_[i], 0, 0);
            lv_obj_set_style_bg_color(eye_[i], lv_color_black(), 0);
            lv_obj_set_style_bg_opa(eye_[i], LV_OPA_COVER, 0);
            pupil_[i] = lv_obj_create(eye_[i]);
            lv_obj_set_size(pupil_[i], kPupilWidth, kPupilHeight);
            lv_obj_set_pos(pupil_[i], PupilX(0), PupilY(kOpenHeight, 0));
            lv_obj_set_style_radius(pupil_[i], LV_RADIUS_CIRCLE, 0);
            lv_obj_set_style_pad_all(pupil_[i], 0, 0);
            lv_obj_set_style_border_width(pupil_[i], 0, 0);
            lv_obj_set_style_bg_color(pupil_[i], lv_color_white(), 0);
            lv_obj_set_style_bg_opa(pupil_[i], LV_OPA_COVER, 0);
        }
        lv_obj_add_flag(eye_layer_, LV_OBJ_FLAG_HIDDEN);
        // Keep Xiaozhi's independent low-battery warning above cosmetic eyes.
        if (low_battery_popup_) lv_obj_move_foreground(low_battery_popup_);
    }

    // The pinned esp_lvgl_port 2.9.x lock is recursive. The priority change
    // and every upstream write are serialized by that same lock, not repaired
    // by a periodic status refresh. Keep the latest real upstream status for
    // recovery (including clock, connection and localized voice states).
    void SetLocalStatus(FaceStatus status) {
        DisplayLockGuard lock(this);
        if (!lock || status == local_status_) return;
        if (local_status_ == FaceStatus::kNormal) RememberNormalStatusLocked();
        local_status_ = status;
        if (status == FaceStatus::kNormal) {
            if (normal_status_ && status_label_)
                OledDisplay::SetStatus(normal_status_->c_str());
            normal_status_.reset();
        } else {
            ApplyPriorityLocked();
        }
    }

    void SetStatus(const char* status) override {
        if (!status) return;
        DisplayLockGuard lock(this);
        if (!lock) return;
        if (local_status_ != FaceStatus::kNormal) {
            normal_status_ = status;
            return;
        }
        OledDisplay::SetStatus(status);
    }

    void ShowNotification(const char* notification, int duration_ms = 3000) override {
        if (!notification) return;
        DisplayLockGuard lock(this);
        if (!lock || local_status_ != FaceStatus::kNormal) return;
        OledDisplay::ShowNotification(notification, duration_ms);
    }

    void ShowNotification(const std::string& notification, int duration_ms = 3000) override {
        ShowNotification(notification.c_str(), duration_ms);
    }

    bool SetEmotion(const char* emotion) override {
        if (!emotion) return false;
        DisplayLockGuard lock(this);
        if (!lock || (FaceStatusBlocksExpression(local_status_) &&
                      std::strcmp(emotion, "neutral") != 0)) return false;
        return OledDisplay::SetEmotion(emotion);
    }

    // The pinned OLED puts the emotion cell on the left when subtitles are
    // shown. A centered temporary overlay would cover the transcript instead.
    // Hide it before publishing text; only a matching removal releases it.
    void SetChatMessage(const char* role, const char* content) override {
        DisplayLockGuard lock(this);
        if (!lock) return;
        subtitle_ = NormalizeSubtitle(content);
        if (!subtitle_.empty()) RenderEyesLocked({});
        OledDisplay::SetChatMessage(role, subtitle_.c_str());
    }

    void RemoveChatMessage(const char* role, const char* content) override {
        if (!content) return;
        DisplayLockGuard lock(this);
        if (!lock) return;
        OledDisplay::RemoveChatMessage(role, content);
        if (NormalizeSubtitle(content) == subtitle_) subtitle_.clear();
    }

    // Keep actual panel I/O under the existing LVGL lock. A subtitle,
    // notification or battery popup is never eligible for idle blanking.
    template <typename Apply>
    void UpdateIdlePower(uint64_t now, bool can_rest, bool sleeping, Apply apply) {
        DisplayLockGuard lock(this);
        if (!lock) return;
        const bool clear = local_status_ == FaceStatus::kNormal && subtitle_.empty() &&
            status_label_ && !lv_obj_has_flag(status_label_, LV_OBJ_FLAG_HIDDEN) &&
            (!low_battery_popup_ || lv_obj_has_flag(low_battery_popup_, LV_OBJ_FLAG_HIDDEN));
        idle_power_.Update(now, can_rest && clear, sleeping, apply);
    }

    void ShowEyes(const EyeFrame& frame) {
        DisplayLockGuard lock(this);
        if (!lock) return;
        RenderEyesLocked(FaceStatusBlocksExpression(local_status_) || !subtitle_.empty()
                             ? EyeFrame{} : frame);
    }

    ~LocalEyeDisplay() override {
        DisplayLockGuard lock(this);
        if (lock && eye_layer_) lv_obj_del(eye_layer_);
    }

private:
    void RememberNormalStatusLocked() {
        if (!normal_status_ && status_label_)
            normal_status_ = lv_label_get_text(status_label_);
    }

    void ApplyPriorityLocked() {
        if (FaceStatusBlocksExpression(local_status_)) RenderEyesLocked({});
        // The base emotion label is initialized together with the status UI.
        if (!status_label_) return;
        if (FaceStatusBlocksExpression(local_status_)) OledDisplay::SetEmotion("neutral");
        const char* status = "";
        switch (local_status_) {
            case FaceStatus::kBodyFault: status = "Body safety stop"; break;
            case FaceStatus::kDockLock: status = "Dock lock: motors off"; break;
            case FaceStatus::kMicPrivacy: status = "Mic privacy ON"; break;
            case FaceStatus::kFaceUnavailable: status = "Face task unavailable"; break;
            case FaceStatus::kVoiceLinkLost: status = "Voice offline"; break;
            case FaceStatus::kNormal: return;
        }
        OledDisplay::SetStatus(status);
    }

    static std::string NormalizeSubtitle(const char* content) {
        std::string text = content ? content : "";
        std::replace(text.begin(), text.end(), '\n', ' ');
        return text;
    }

    void RenderEyesLocked(EyeFrame frame) {
        using namespace face_eye_geometry;
        if (!eye_layer_) return;
        if (!frame.visible) frame = {};
        frame.x = std::clamp<int>(frame.x, -kGazeExtent, kGazeExtent);
        frame.y = std::clamp<int>(frame.y, -kGazeExtent, kGazeExtent);
        frame.lid_height = std::clamp<int>(frame.lid_height, kClosedHeight, kOpenHeight);
        if (frame_known_ && frame.visible == last_.visible &&
            frame.closed == last_.closed && frame.x == last_.x &&
            frame.y == last_.y && frame.lid_height == last_.lid_height) return;
        if (!frame.visible) {
            lv_obj_add_flag(eye_layer_, LV_OBJ_FLAG_HIDDEN);
        } else {
            for (int i = 0; i < kEyeCount; ++i) {
                const int height = frame.closed ? kClosedHeight : frame.lid_height;
                lv_obj_set_size(eye_[i], kEyeWidth, height);
                lv_obj_set_pos(eye_[i], EyeX(i), EyeY(height));
                if (height < kPupilMinEyeHeight) {
                    lv_obj_add_flag(pupil_[i], LV_OBJ_FLAG_HIDDEN);
                } else {
                    lv_obj_set_pos(pupil_[i], PupilX(frame.x), PupilY(height, frame.y));
                    lv_obj_remove_flag(pupil_[i], LV_OBJ_FLAG_HIDDEN);
                }
            }
            lv_obj_remove_flag(eye_layer_, LV_OBJ_FLAG_HIDDEN);
        }
        last_ = frame;
        frame_known_ = true;
    }

    lv_obj_t* eye_layer_ = nullptr;
    lv_obj_t* eye_[face_eye_geometry::kEyeCount] = {};
    lv_obj_t* pupil_[face_eye_geometry::kEyeCount] = {};
    FaceIdlePower idle_power_;
    EyeFrame last_{};
    bool frame_known_ = false;
    FaceStatus local_status_ = FaceStatus::kNormal;
    std::optional<std::string> normal_status_;
    std::string subtitle_;
};
}  // namespace desk_robot
