#pragma once

#include <cstdint>
#include <optional>

#include <esp_lcd_panel_interface.h>
#include <lvgl.h>

namespace desk_robot {

// Sense's single, synchronous I2C SSD1306 only. The esp_lvgl_port 2.9.x
// monochrome flush ignores draw_bitmap's result. ESP-IDF calls its color
// completion callback only on success, so an error otherwise strands LVGL.
// Keep the existing port's conversion, buffer and successful callback intact.
class FacePanelFlushRecovery {
public:
    static constexpr uint64_t kRetryMs = 1000;

    esp_err_t Install(esp_lcd_panel_t* panel, int width, int height) {
        if (!panel || !panel->draw_bitmap || panel->user_data || original_ ||
            width <= 0 || height <= 0) return ESP_ERR_INVALID_STATE;
        width_ = width;
        height_ = height;
        original_ = panel->draw_bitmap;
        panel->user_data = this;
        panel->draw_bitmap = Draw;
        return ESP_OK;
    }

    // Call under the existing LVGL lock, AFTER applying the latest UI status.
    // Invalidate the scene, never replay a cached pixel buffer or old subtitle.
    void Retry(uint64_t now_ms) {
        if (!pending_ || (last_retry_ && now_ms >= *last_retry_ &&
                         now_ms - *last_retry_ < kRetryMs)) return;
        auto* display = lv_display_get_default();
        if (!display) return;
        auto* screen = lv_display_get_screen_active(display);
        if (!screen) return;
        last_retry_ = now_ms;
        lv_obj_invalidate(screen);
    }

private:
    static esp_err_t Draw(esp_lcd_panel_t* panel, int x1, int y1, int x2, int y2,
                          const void* pixels) {
        auto& self = *static_cast<FacePanelFlushRecovery*>(panel->user_data);
        const auto result = self.original_(panel, x1, y1, x2, y2, pixels);
        if (result != ESP_OK) {
            self.pending_ = true;
            // Synchronous I2C returned without its normal completion callback.
            // This releases the LVGL buffer; it is NOT a successful panel receipt.
            if (auto* display = lv_display_get_default()) lv_display_flush_ready(display);
        } else if (x1 == 0 && y1 == 0 && x2 == self.width_ && y2 == self.height_) {
            self.pending_ = false;
            self.last_retry_.reset();
        }
        return result;
    }

    decltype(esp_lcd_panel_t::draw_bitmap) original_ = nullptr;
    int width_ = 0;
    int height_ = 0;
    bool pending_ = false;
    std::optional<uint64_t> last_retry_;
};
}  // namespace desk_robot
