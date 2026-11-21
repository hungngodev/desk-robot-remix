#pragma once

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
        lv_obj_set_pos(eye_layer_, 0, 16);
        lv_obj_set_size(eye_layer_, 32, 48);
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

    void ShowEyes(const EyeFrame& frame) {
        if (frame_known_ && frame.visible == last_.visible &&
            frame.closed == last_.closed && frame.x == last_.x &&
            frame.y == last_.y) return;
        DisplayLockGuard lock(this);
        if (!lock || !eye_layer_) return;
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

    ~LocalEyeDisplay() override {
        DisplayLockGuard lock(this);
        if (lock && eye_layer_) lv_obj_del(eye_layer_);
    }

private:
    lv_obj_t* eye_layer_ = nullptr;
    lv_obj_t* eye_[2] = {nullptr, nullptr};
    lv_obj_t* pupil_[2] = {nullptr, nullptr};
    EyeFrame last_{};
    bool frame_known_ = false;
};
}  // namespace desk_robot
