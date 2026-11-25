#pragma once

#include <algorithm>
#include <atomic>
#include <cstring>
#include <string>

#include "display/oled_display.h"
#include "face_eye_animator.hpp"

// Short eye gestures cover only Xiaozhi's 32-pixel emotion slot.
// All display mutations share Xiaozhi's LVGL lock; safety status, subtitles,
// microphone and speaker remain upstream-owned. No actuator API is reachable.
namespace desk_robot {
class LocalEyeDisplay final : public OledDisplay {
public:
    using OledDisplay::OledDisplay;

    void SetupUI() override {
        OledDisplay::SetupUI();
        DisplayLockGuard lock(this);
        if (!lock || eye_layer_ || width() != 128 || height() != 64) return;
        eye_layer_ = lv_obj_create(lv_screen_active());
        lv_obj_set_size(eye_layer_, 32, 48);
        // Xiaozhi's 128x64 idle emotion cell is 32px wide, centered in
        // the content row. Cover that cell without obscuring its top 16px
        // network/voice status bar or allocating another display surface.
        lv_obj_align(eye_layer_, LV_ALIGN_TOP_MID, 0, 16);
        lv_obj_set_style_radius(eye_layer_, 0, 0);
        lv_obj_set_style_pad_all(eye_layer_, 0, 0);
        lv_obj_set_style_border_width(eye_layer_, 0, 0);
        lv_obj_set_style_bg_color(eye_layer_, lv_color_white(), 0);
        lv_obj_set_style_bg_opa(eye_layer_, LV_OPA_COVER, 0);
        lv_obj_set_scrollbar_mode(eye_layer_, LV_SCROLLBAR_MODE_OFF);
        for (int i = 0; i < 2; ++i) {
            eye_[i] = lv_obj_create(eye_layer_);
            lv_obj_set_size(eye_[i], 11, 14);
            lv_obj_set_pos(eye_[i], 3 + i * 15, 17);
            lv_obj_set_style_radius(eye_[i], LV_RADIUS_CIRCLE, 0);
            lv_obj_set_style_pad_all(eye_[i], 0, 0);
            lv_obj_set_style_border_width(eye_[i], 0, 0);
            lv_obj_set_style_bg_color(eye_[i], lv_color_black(), 0);
            lv_obj_set_style_bg_opa(eye_[i], LV_OPA_COVER, 0);
            pupil_[i] = lv_obj_create(eye_[i]);
            lv_obj_set_size(pupil_[i], 3, 4);
            lv_obj_set_pos(pupil_[i], 4, 5);
            lv_obj_set_style_radius(pupil_[i], LV_RADIUS_CIRCLE, 0);
            lv_obj_set_style_pad_all(pupil_[i], 0, 0);
            lv_obj_set_style_border_width(pupil_[i], 0, 0);
            lv_obj_set_style_bg_color(pupil_[i], lv_color_white(), 0);
            lv_obj_set_style_bg_opa(pupil_[i], LV_OPA_COVER, 0);
        }
        lv_obj_add_flag(eye_layer_, LV_OBJ_FLAG_HIDDEN);
    }

    // The pinned esp_lvgl_port 2.9.x lock is recursive. Hold the existing
    // lock across arbitration and base display calls so a concurrent voice
    // emotion cannot slip through after a fault has been observed.
    void SetBodyFault(bool active) {
        if (body_fault_.load(std::memory_order_acquire) == active) return;
        DisplayLockGuard lock(this);
        if (!lock) return;  // FaceTask retries the transition on its next tick.
        body_fault_.store(active, std::memory_order_release);
        if (active) {
            RenderEyesLocked({});
            OledDisplay::SetEmotion("neutral");
        }
    }

    bool SetEmotion(const char* emotion) override {
        if (!emotion) return false;
        DisplayLockGuard lock(this);
        if (!lock || (body_fault_.load(std::memory_order_acquire) &&
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

    void ShowEyes(const EyeFrame& frame) {
        DisplayLockGuard lock(this);
        if (!lock) return;
        RenderEyesLocked(body_fault_.load(std::memory_order_acquire) || !subtitle_.empty()
                             ? EyeFrame{} : frame);
    }

    ~LocalEyeDisplay() override {
        DisplayLockGuard lock(this);
        if (lock && eye_layer_) lv_obj_del(eye_layer_);
    }

private:
    static std::string NormalizeSubtitle(const char* content) {
        std::string text = content ? content : "";
        std::replace(text.begin(), text.end(), '\n', ' ');
        return text;
    }

    void RenderEyesLocked(EyeFrame frame) {
        if (!eye_layer_) return;
        if (!frame.visible) frame = {};
        frame.x = std::clamp<int>(frame.x, -3, 3);
        frame.y = std::clamp<int>(frame.y, -3, 3);
        if (frame_known_ && frame.visible == last_.visible &&
            frame.closed == last_.closed && frame.x == last_.x &&
            frame.y == last_.y) return;
        if (!frame.visible) {
            lv_obj_add_flag(eye_layer_, LV_OBJ_FLAG_HIDDEN);
        } else {
            for (int i = 0; i < 2; ++i) {
                lv_obj_set_size(eye_[i], 11, frame.closed ? 2 : 14);
                lv_obj_set_pos(eye_[i], 3 + i * 15, frame.closed ? 23 : 17);
                if (frame.closed) {
                    lv_obj_add_flag(pupil_[i], LV_OBJ_FLAG_HIDDEN);
                } else {
                    lv_obj_set_pos(pupil_[i], 4 + frame.x, 5 + frame.y);
                    lv_obj_remove_flag(pupil_[i], LV_OBJ_FLAG_HIDDEN);
                }
            }
            lv_obj_remove_flag(eye_layer_, LV_OBJ_FLAG_HIDDEN);
        }
        last_ = frame;
        frame_known_ = true;
    }

    lv_obj_t* eye_layer_ = nullptr;
    lv_obj_t* eye_[2] = {nullptr, nullptr};
    lv_obj_t* pupil_[2] = {nullptr, nullptr};
    EyeFrame last_{};
    bool frame_known_ = false;
    std::atomic<bool> body_fault_{false};
    std::string subtitle_;
};
}  // namespace desk_robot
