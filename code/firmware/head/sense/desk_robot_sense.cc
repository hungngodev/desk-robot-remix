// Board integration using Xiaozhi's bread-compact-wifi and S3CAM initializers.
// Camera, SSD1306 display, PDM input and I2S output remain upstream drivers.
#include "wifi_board.h"
#include "sense_reference_codec.h"
#include "display/oled_display.h"
#include "application.h"
#include "button.h"
#include "config.h"
#include "esp32_camera.h"
#include "robot_bridge.h"
#include "stackchan_behavior.hpp"
#include "face_eye_display.hpp"
#include "face_mood_morph.hpp"
#include "led/single_led.h"
#include "sdkconfig.h"
#if CONFIG_USE_AUDIO_DEBUGGER
#error "Sense raw UDP audio debugger is forbidden; use consented one-shot PCM capture"
#endif
#ifdef CONFIG_DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED
#include <wifi_manager.h>
#endif

#include <esp_timer.h>
#include <esp_lvgl_port.h>
#include <esp_log.h>
#ifdef CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED
#include <esp_event.h>
#include <esp_wifi.h>
#endif
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <algorithm>
#include <cstdint>
#include <atomic>
#include <mutex>
#include <string_view>
#include <driver/i2c_master.h>
#include <esp_lcd_panel_io.h>
#include <esp_lcd_panel_ops.h>
#include <esp_lcd_panel_vendor.h>
#include <driver/gpio.h>

// Pinned iot_button dispatches these callbacks serially from its button task.
// Only a matching debounced press/release/single-click may restore consent.
class BootPrivacyGesture {
public:
    bool PressDown() {
        click_ready_ = false;
        if (pressed_) {
            cancelled_ = true;
            return false;
        }
        pressed_ = true;
        cancelled_ = false;
        return true;
    }
    void PressUp() {
        if (!pressed_) {
            click_ready_ = false;
            return;
        }
        pressed_ = false;
        click_ready_ = !cancelled_;
    }
    bool Held() const { return pressed_ && !cancelled_; }
    void Cancel() {
        cancelled_ = true;
        click_ready_ = false;
    }
    bool TakeClick() {
        const bool accepted = !pressed_ && click_ready_;
        click_ready_ = false;
        return accepted;
    }
private:
    bool pressed_ = false;
    bool cancelled_ = false;
    bool click_ready_ = false;
};

// Publish a complete WROOM observation, never independently sampled flags.
struct BodyFaceStatus {
    bool valid = false;
    bool fault = true;
    bool dock_lockout = false;
    uint64_t at_ms = 0;

    bool Fresh(uint64_t now_ms) const {
        return valid && now_ms >= at_ms && now_ms - at_ms <= 1200U;
    }
};

class BodyFaceState {
public:
    void Publish(BodyFaceStatus status) {
        std::lock_guard<std::mutex> lock(mutex_);
        status_ = status;
    }
    BodyFaceStatus Read() {
        std::lock_guard<std::mutex> lock(mutex_);
        return status_;
    }
private:
    std::mutex mutex_;
    BodyFaceStatus status_{};
};

// The startup delay is absolute uptime, not a wrapping 32-bit face clock.
constexpr bool AudioListenRetryDue(uint64_t uptime_ms, uint64_t last_attempt_ms) {
    return uptime_ms >= 10000U && uptime_ms >= last_attempt_ms &&
           uptime_ms - last_attempt_ms >= 5000U;
}

// Cosmetic updates must not wait behind the LVGL worker's I2C flush.
// The pinned port mutex is recursive; nested upstream display calls reuse it.
class FaceRenderGuard {
public:
    FaceRenderGuard() : acquired_(lvgl_port_lock(1)) {}
    ~FaceRenderGuard() { if (acquired_) lvgl_port_unlock(); }
    explicit operator bool() const { return acquired_; }
    FaceRenderGuard(const FaceRenderGuard&) = delete;
    FaceRenderGuard& operator=(const FaceRenderGuard&) = delete;
private:
    bool acquired_;
};

class DeskRobotSenseBoard : public WifiBoard {
private:
    i2c_master_bus_handle_t display_i2c_bus_ = nullptr;
    // Non-owning aliases: the upstream OledDisplay owns both handles.
    esp_lcd_panel_io_handle_t display_panel_io_ = nullptr;
    esp_lcd_panel_handle_t display_panel_ = nullptr;
    Display* display_ = nullptr;
    desk_robot::LocalEyeDisplay* local_eye_display_ = nullptr;
    desk_robot::FaceEyeAnimator eye_animator_{};
    Esp32Camera* camera_ = nullptr;
    Button boot_button_;
    // Pinned Stackchan-agent HSM controls OLED mood only, NEVER tracks/claw.
    stackchan::behavior::HsmBehavior face_behavior_{0x5a17};
    bool face_was_speaking_ = false;
    desk_robot::Bridge* body_bridge_ = nullptr;  // existing single UART owner
    // A 350 ms UART timeout cannot block the OLED animation task.
    // Keep one actual bridge UART owner; only read-only polling moves tasks.
    BodyFaceState body_face_state_;
    std::mutex network_tasks_mutex_;
    TaskHandle_t face_task_ = nullptr;
    TaskHandle_t body_poll_task_ = nullptr;
#ifdef CONFIG_DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED
    // The operator can stop mic streaming with BOOT. Do not silently
    // restart listening after that explicit human action.
    std::atomic<bool> audio_operator_touched_{false};
    std::atomic<bool> audio_operator_muted_{false};
    // This press latches mute before the release-based click event runs.
    std::atomic<bool> boot_press_muted_{false};
    BootPrivacyGesture boot_privacy_gesture_;
    bool continuous_audio_started_ = false;
    uint64_t last_audio_listen_attempt_ms_ = 0;
    uint32_t last_audio_failure_epoch_seen_ = 0;
#ifdef CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED
    std::mutex bench_gesture_mutex_;
    desk_robot::FreshBenchPcmConsent bench_hold_consent_{};
    std::atomic<bool> bench_wifi_events_ready_{false};

    void RevokeBenchConsent() {
        std::lock_guard<std::mutex> lock(bench_gesture_mutex_);
        bench_hold_consent_.Revoke();
        static_cast<SenseReferenceCodec*>(GetAudioCodec())->AbortBenchPcmCapture();
    }

    static void BenchWifiEvent(void* context, esp_event_base_t, int32_t event, void*) {
        if (event == WIFI_EVENT_STA_DISCONNECTED || event == WIFI_EVENT_STA_STOP)
            static_cast<DeskRobotSenseBoard*>(context)->RevokeBenchConsent();
    }
#endif
#endif

    static const char* MoodName(stackchan::behavior::Mood mood) {
        using stackchan::behavior::Mood;
        switch (mood) {
            case Mood::kSmile: return "happy";
            case Mood::kSad: return "sad";
            case Mood::kSleepy: return "sleepy";
            case Mood::kDoubt: return "thinking";
            case Mood::kSurprised: return "surprised";
            case Mood::kAngry: return "angry";
            default: return "neutral";
        }
    }

    static const char* CosmeticMoodName(desk_robot::CosmeticMood mood) {
        using desk_robot::CosmeticMood;
        switch (mood) {
            case CosmeticMood::kNeutral: return "neutral";
            case CosmeticMood::kHappy: return "happy";
            case CosmeticMood::kThinking: return "thinking";
            case CosmeticMood::kSurprised: return "surprised";
            default: return "neutral";
        }
    }

    static void BodyPollTask(void* context) {
        auto* board = static_cast<DeskRobotSenseBoard*>(context);
        while (true) {
            // Blocking WROOM reads remain off the local OLED scheduler.
            const auto body = board->body_bridge_->PollInteraction();
            if (body.valid) {
                const uint64_t at_ms =
                    static_cast<uint64_t>(esp_timer_get_time() / 1000);
                board->body_face_state_.Publish({true, body.fault, body.dock_lockout, at_ms});
                // WROOM/CAP touch counters remain available to the Mac's
                // unified sensor timeline. They must not force a local
                // happy face or nod before the contextual mood owner decides.
            } else {
                // A timeout or malformed status cannot leave healthy eyes.
                board->body_face_state_.Publish({});
            }
            vTaskDelay(pdMS_TO_TICKS(300));
        }
    }

    static void FaceTask(void* context) {
        auto* board = static_cast<DeskRobotSenseBoard*>(context);
        using namespace stackchan::behavior;
#if defined(CONFIG_DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED) && defined(CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED)
        uint32_t last_bench_failure_epoch = 0;
#endif
        bool last_face_available = false;
        bool last_priority_active = false;
        bool model_mood_active = false;
        const char* local_mood = "neutral";
        desk_robot::FaceMoodMorph mood_morph;
        desk_robot::FaceMouthAnimator mouth_animator;
        uint32_t model_mood_started_ms = 0;
        while (true) {
            const uint32_t now_ms = static_cast<uint32_t>(esp_timer_get_time() / 1000);
            // Copy under a short independent lock, never held across UART or OLED I/O.
            const auto body = board->body_face_state_.Read();
            const uint64_t uptime_ms =
                static_cast<uint64_t>(esp_timer_get_time() / 1000);
            const bool body_fresh = body.Fresh(uptime_ms);
            // A stalled polling task cannot preserve an old healthy report.
            const bool body_unhealthy = !body_fresh || body.fault;
            // A dock-contact fault is still a mandatory local motor STOP.
            // Distinguish only a fresh, coherent WROOM contact report.
            const bool dock_lockout = body_fresh && body_unhealthy && body.dock_lockout;
            // Touch is a physical observation, not an unconditional mood.
            // The Mac may request a transient face cue through the existing
            // consented cosmetic route; WROOM independently owns local STOP.
            // Consume a visual cue even during a fault so it cannot
            // replay as a fresh sighting on recovery. The existing
            // Stackchan HSM owns optional idle expression, not motion.
            if (board->body_bridge_ && board->body_bridge_->TakePersonCue() &&
                !body_unhealthy) {
                board->face_behavior_.pushEvent(
                    Event(EventType::kPersonDetected));
            }
            auto& app = Application::GetInstance();
            const auto device_state = app.GetDeviceState();
#ifdef CONFIG_DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED
            // Upstream Xiaozhi normally streams mic PCM only AFTER wake.
            // With explicit audio consent, reuse its existing full-duplex
            // realtime AEC transport. No new mic task, codec or WebSocket.
            // A server WebSocket can close and Xiaozhi returns to Idle
            // without a WiFi-disconnect edge. Retrying only once per WiFi
            // epoch would leave the consented live microphone silent forever.
            // Throttle reconnection through the SAME Xiaozhi event owner;
            // NEVER restart after BOOT touched privacy for this boot.
            const bool wifi_connected = WifiManager::GetInstance().IsConnected();
            if (!wifi_connected) {
                board->continuous_audio_started_ = false;
            }
            const uint32_t failure_epoch = app.GetSenseAudioFailureEpoch();
            const bool voice_link_lost = !wifi_connected || app.GetSenseAudioLinkUnavailable();
#ifdef CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED
            if (failure_epoch != last_bench_failure_epoch) {
                last_bench_failure_epoch = failure_epoch;
                board->RevokeBenchConsent();
            }
#endif
            // Initial launch or a proved channel closure/open failure ONLY.
            // A healthy intentional Idle transition must not force a new
            // session. Space every attempt by at least 5s, including WiFi flaps.
            const bool failed_since_attempt =
                failure_epoch != board->last_audio_failure_epoch_seen_;
            if ((!board->continuous_audio_started_ || failed_since_attempt) &&
                    AudioListenRetryDue(uptime_ms, board->last_audio_listen_attempt_ms_)) {
                if (!board->audio_operator_touched_.load()
                        && wifi_connected
                        && device_state == kDeviceStateIdle
                        && app.GetAecMode() == kAecOnDeviceSide) {
                    board->last_audio_failure_epoch_seen_ = failure_epoch;
                    board->continuous_audio_started_ = true;
                    board->last_audio_listen_attempt_ms_ = uptime_ms;
                    app.ToggleChatState();  // existing Xiaozhi realtime listen
                }
            }
#else
            const bool voice_link_lost = false;
#endif
            const bool speaking = device_state == kDeviceStateSpeaking;
            if (speaking && !board->face_was_speaking_) {
                board->face_behavior_.pushEvent(Event(EventType::kSpeakRequest, ""));
            } else if (!speaking && board->face_was_speaking_) {
                board->face_behavior_.pushEvent(Event(EventType::kSpeechFinished));
            }
            board->face_was_speaking_ = speaking;
            const Observation obs{now_ms};
            const Action action = board->face_behavior_.update(obs);
            // The upstream OLED keeps status text and emotion in separate
            // LVGL labels. Preserve Xiaozhi's Speaking/Listening text while
            // allowing silent cosmetic mood in continuously listening mode.
            // A normal wake-only build still reserves its listening UI.
            const bool idle = device_state == kDeviceStateIdle;
#ifdef CONFIG_DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED
            bool face_available = idle || device_state == kDeviceStateListening;
            if (voice_link_lost && !speaking) face_available = true;
#else
            const bool face_available = idle;
#endif
#ifdef CONFIG_DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED
            const bool mic_privacy_on = board->audio_operator_muted_.load(
                std::memory_order_acquire);
#else
            const bool mic_privacy_on = false;
#endif
            const auto local_status = desk_robot::SelectFaceStatus(
                body_unhealthy, dock_lockout, mic_privacy_on, voice_link_lost);
            const bool priority_active = desk_robot::FaceStatusBlocksExpression(local_status);
            if (priority_active || !face_available) model_mood_active = false;
            const bool mouth_allowed = speaking && !priority_active && !voice_link_lost;
            const auto speech_level = mouth_allowed ?
                static_cast<SenseReferenceCodec*>(board->GetAudioCodec())->ReadSpeechLevel(
                    esp_timer_get_time()) : desk_robot::SpeechLevel{};
            {
                FaceRenderGuard render_lock;
                // Retain the newest unexpired cue during transient OLED lock
                // contention. Drain suppressed cues even if the lock is busy,
                // so safety, speech or link recovery cannot replay stale moods.
                const auto requested_mood = board->body_bridge_ &&
                    (render_lock || priority_active || !face_available ||
                     voice_link_lost || board->display_ == nullptr) ?
                    board->body_bridge_->TakeCosmeticMoodCue() :
                    desk_robot::CosmeticMood::kNone;
                if (!render_lock) {
                    // Drop cosmetic work rather than delaying the next audio retry.
                    // Reconcile the latest status and HSM mood on the next frame.
                    last_face_available = false;
                    model_mood_active = false;
                    mood_morph.Step(now_ms, local_mood, false);
                    mouth_animator.Step({}, false);
                    board->eye_animator_.Step(
                        now_ms, Motion::kNone, false,
                        priority_active || !isAwake(board->face_behavior_.state()));
                } else {
                    // This owns the status label and neutral face under the LVGL lock.
                    // Upstream clock, notifications and voice cannot replace it.
                    if (board->local_eye_display_ != nullptr)
                        board->local_eye_display_->SetLocalStatus(local_status);
                    if (face_available && board->display_ != nullptr) {
                        // Only the Mac's CURRENT context decision may request a
                        // transient mood. The local idle HSM takes over afterward.
                        // These bytes never reach WROOM, motors, Opus or microphones.
                        if (priority_active) {
                            // Keep a nonemotional neutral safety face instead of
                            // prescribing sadness for every independent WROOM fault.
                            // The factual STOP status above remains visible, and
                            // optional HSM/LLM moods cannot override the safety cue.
                            model_mood_active = false;
                        } else if (!voice_link_lost &&
                                   requested_mood != desk_robot::CosmeticMood::kNone) {
                            local_mood = CosmeticMoodName(requested_mood);
                            board->display_->SetEmotion(CosmeticMoodName(requested_mood));
                            model_mood_active = true;
                            model_mood_started_ms = now_ms;
                        } else if (voice_link_lost || !model_mood_active ||
                                   now_ms - model_mood_started_ms >= 1600U) {
                            if (last_priority_active || model_mood_active ||
                                !last_face_available || action.set_mood) {
                                local_mood = MoodName(board->face_behavior_.mood());
                                board->display_->SetEmotion(
                                    MoodName(board->face_behavior_.mood()));
                            }
                            model_mood_active = false;
                        }
                    }
                    // Idle gaze yields to Mac cues; the bounded cosmetic mood
                    // bridge can ease either local or Mac expressions. Safety and
                    // voice suppress idle gestures immediately. Only fresh digital
                    // speaker activity can open the optional cosmetic mouth.
                    if (board->local_eye_display_ != nullptr) {
                        auto eyes = board->eye_animator_.Step(
                            now_ms, action.motion,
                            face_available && !priority_active && !model_mood_active,
                            priority_active || !isAwake(board->face_behavior_.state()));
                        const auto height = mood_morph.Step(
                            now_ms, local_mood, face_available && !priority_active,
                            eyes.visible);
                        eyes = desk_robot::BlendMoodAperture(eyes, height);
                        eyes.mouth_height = mouth_animator.Step(speech_level, mouth_allowed);
                        if (eyes.mouth_height != 0) eyes.visible = true;
                        board->local_eye_display_->ShowEyes(eyes);
                        const auto hsm_state = board->face_behavior_.state();
                        const bool sleeping = hsm_state == State::kSleeping;
                        board->local_eye_display_->UpdateIdlePower(
                            uptime_ms, idle && !priority_active && !model_mood_active &&
                                (hsm_state == State::kIdle || sleeping), sleeping,
                            [board](desk_robot::FacePanelMode mode) {
                                return board->ApplyFacePanelMode(mode);
                            });
                    }
                    // Restore the current HSM mood after either local priority clears.
                    last_priority_active = priority_active;
                    last_face_available = face_available;
                }
            }
            vTaskDelay(pdMS_TO_TICKS(100));
        }
    }

    bool ApplyFacePanelMode(desk_robot::FacePanelMode mode) {
        using desk_robot::FacePanelMode;
        if (!display_panel_ || !display_panel_io_) return false;
        if (mode == FacePanelMode::kOff)
            return esp_lcd_panel_disp_on_off(display_panel_, false) == ESP_OK;
        // SSD1306 SETCONTRAST (0x81). Explicit provisional defaults; the
        // actual panel brightness/current still requires bench measurement.
        const uint8_t contrast = mode == FacePanelMode::kDim ? 0x20 :
            (mode == FacePanelMode::kSoftDim ? 0x50 : 0x80);
        const auto contrast_result =
            esp_lcd_panel_io_tx_param(display_panel_io_, 0x81, &contrast, sizeof(contrast));
        // Always attempt wake even when contrast fails; the policy retries.
        const auto wake_result = esp_lcd_panel_disp_on_off(display_panel_, true);
        return contrast_result == ESP_OK && wake_result == ESP_OK;
    }

    void InitializeDisplay() {
        i2c_master_bus_config_t bus_config = {};
        bus_config.i2c_port = DISPLAY_I2C_PORT;
        bus_config.sda_io_num = DISPLAY_SDA_PIN;
        bus_config.scl_io_num = DISPLAY_SCL_PIN;
        bus_config.clk_source = I2C_CLK_SRC_DEFAULT;
        bus_config.glitch_ignore_cnt = 7;
        bus_config.flags.enable_internal_pullup = true;
        ESP_ERROR_CHECK(i2c_new_master_bus(&bus_config, &display_i2c_bus_));

        esp_lcd_panel_io_i2c_config_t io_config = {};
        io_config.dev_addr = 0x3C;
        io_config.scl_speed_hz = 400000;
        // A full 1024-byte frame needs about 23 ms of wire time at 400 kHz.
        // Bound each transfer even if SDA/SCL stalls; zero waits indefinitely.
        io_config.transaction_timeout_ms = 50;
        io_config.control_phase_bytes = 1;
        io_config.dc_bit_offset = 6;
        io_config.lcd_cmd_bits = 8;
        io_config.lcd_param_bits = 8;
        esp_lcd_panel_io_handle_t panel_io = nullptr;
        ESP_ERROR_CHECK(esp_lcd_new_panel_io_i2c(display_i2c_bus_, &io_config, &panel_io));
        esp_lcd_panel_dev_config_t panel_config = {};
        panel_config.reset_gpio_num = GPIO_NUM_NC;
        panel_config.bits_per_pixel = 1;
        esp_lcd_panel_handle_t panel = nullptr;
        esp_lcd_panel_ssd1306_config_t ssd1306_config = {};
        ssd1306_config.height = DISPLAY_HEIGHT;
        panel_config.vendor_config = &ssd1306_config;
        ESP_ERROR_CHECK(esp_lcd_new_panel_ssd1306(panel_io, &panel_config, &panel));
        ESP_ERROR_CHECK(esp_lcd_panel_reset(panel));
        ESP_ERROR_CHECK(esp_lcd_panel_init(panel));
        ESP_ERROR_CHECK(esp_lcd_panel_invert_color(panel, false));
        ESP_ERROR_CHECK(esp_lcd_panel_disp_on_off(panel, true));
        local_eye_display_ = new desk_robot::LocalEyeDisplay(
            panel_io, panel, DISPLAY_WIDTH, DISPLAY_HEIGHT,
            DISPLAY_MIRROR_X, DISPLAY_MIRROR_Y);
        display_panel_io_ = panel_io;
        display_panel_ = panel;
        display_ = local_eye_display_;
    }

    void InitializeCamera() {
        camera_config_t config = {};
        config.pin_d0 = CAMERA_PIN_D0;
        config.pin_d1 = CAMERA_PIN_D1;
        config.pin_d2 = CAMERA_PIN_D2;
        config.pin_d3 = CAMERA_PIN_D3;
        config.pin_d4 = CAMERA_PIN_D4;
        config.pin_d5 = CAMERA_PIN_D5;
        config.pin_d6 = CAMERA_PIN_D6;
        config.pin_d7 = CAMERA_PIN_D7;
        config.pin_xclk = CAMERA_PIN_XCLK;
        config.pin_pclk = CAMERA_PIN_PCLK;
        config.pin_vsync = CAMERA_PIN_VSYNC;
        config.pin_href = CAMERA_PIN_HREF;
        config.pin_sccb_sda = CAMERA_PIN_SIOD;
        config.pin_sccb_scl = CAMERA_PIN_SIOC;
        config.sccb_i2c_port = CAMERA_SCCB_I2C_PORT;
        config.pin_pwdn = CAMERA_PIN_PWDN;
        config.pin_reset = CAMERA_PIN_RESET;
        config.xclk_freq_hz = XCLK_FREQ_HZ;
        // The pinned Xiaozhi Esp32Camera handles PIXFORMAT_JPEG natively.
        // Avoid VGA RGB565 copies and software JPEG compression on the S3:
        // leave CPU headroom for PDM AEC, Opus and emergency audio flush.
        // Espressif esp32-camera uses continuous JPEG acquisition only with
        // two or more framebuffers. LATEST discards queued old frames, so a
        // fresh MJPEG subscription cannot inherit an old single-buffer image.
        // Only one framebuffer is application-visible in LATEST mode.
        // Real simultaneous mic/AEC/stream throughput and PSRAM pressure
        // still require physical stress tests before camera acceptance.
        config.pixel_format = PIXFORMAT_JPEG;
        config.frame_size = FRAMESIZE_VGA;
        config.jpeg_quality = 12;
        config.fb_count = 2;
        config.fb_location = CAMERA_FB_IN_PSRAM;
        config.grab_mode = CAMERA_GRAB_LATEST;
        camera_ = new Esp32Camera(config);
    }

public:
    DeskRobotSenseBoard() : boot_button_(BOOT_BUTTON_GPIO) {
        // Weighted HSM idle candidates remain spontaneous; keep optional
        // gaze picks in a human-scale 6 to 15 second range.
        face_behavior_.pick_min_ms = 6000;
        face_behavior_.pick_max_ms = 15000;
        // Keep the unused SD device deselected before driving its shared SPI pins.
        // No card may be inserted while GPIO7/8 are used for amplifier clocks/data.
        ESP_ERROR_CHECK(gpio_set_direction(SD_CARD_CS_GPIO, GPIO_MODE_OUTPUT));
        ESP_ERROR_CHECK(gpio_set_level(SD_CARD_CS_GPIO, 1));
        InitializeDisplay();
        InitializeCamera();
#ifdef CONFIG_DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED
        // Pinned Xiaozhi OnClick is a release event. Privacy must take effect
        // at button press-down, including for a long held BOOT button.
        boot_button_.OnPressDown([this]() {
            audio_operator_touched_.store(true, std::memory_order_release);
            if (!boot_privacy_gesture_.PressDown()) return;
            const bool already_muted = audio_operator_muted_.exchange(
                true, std::memory_order_acq_rel);
            boot_press_muted_.store(!already_muted, std::memory_order_release);
            if (already_muted) return;  // A deliberate second tap unmutes on release.
            auto& app = Application::GetInstance();
            const auto state = app.GetDeviceState();
            // Gate queued Opus and actual PDM acquisition BEFORE any audio abort.
            app.SetSenseMicrophonePrivacyMuted(true);
            static_cast<SenseReferenceCodec*>(GetAudioCodec())
                ->SetMicrophonePrivacyMuted(true);
            if (state == kDeviceStateConnecting) {
                app.SetDeviceState(kDeviceStateIdle);
            }
            app.StopListening();
#ifdef CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED
            {
                std::lock_guard<std::mutex> lock(bench_gesture_mutex_);
                bench_hold_consent_.Revoke();
            }
#endif
        });
        boot_button_.OnPressUp([this]() { boot_privacy_gesture_.PressUp(); });
#ifdef CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED
        boot_button_.OnLongPress([this]() {
            // Hold only while ALREADY muted, then release and deliberately tap.
            const bool eligible = boot_privacy_gesture_.Held() &&
                !boot_press_muted_.load(std::memory_order_acquire);
            boot_privacy_gesture_.Cancel();
            std::lock_guard<std::mutex> lock(bench_gesture_mutex_);
            bench_hold_consent_.Revoke();
            if (eligible && audio_operator_muted_.load(std::memory_order_acquire) &&
                bench_wifi_events_ready_.load(std::memory_order_acquire) &&
                WifiManager::GetInstance().IsConnected())
                bench_hold_consent_.Grant(esp_timer_get_time());
        });
        boot_button_.OnDoubleClick([this]() {
            boot_privacy_gesture_.Cancel();
            RevokeBenchConsent();
        });
#else
        boot_button_.OnLongPress([this]() { boot_privacy_gesture_.Cancel(); });
        boot_button_.OnDoubleClick([this]() { boot_privacy_gesture_.Cancel(); });
#endif
#endif
        boot_button_.OnClick([this]() {
#ifdef CONFIG_DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED
            // Orphan, repeated or held-button clicks cannot restore consent.
            if (!boot_privacy_gesture_.TakeClick() ||
                gpio_get_level(BOOT_BUTTON_GPIO) == 0) return;
#endif
            auto& app = Application::GetInstance();
            const auto state = app.GetDeviceState();
            if (state == kDeviceStateStarting) {
#ifdef CONFIG_DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED
                boot_press_muted_.store(false, std::memory_order_release);
#endif
                EnterWifiConfigMode();
                return;
            }
#ifdef CONFIG_DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED
            // The first press already muted and cancelled listening. A
            // release MUST NOT turn the microphone back on in that same tap.
            if (boot_press_muted_.exchange(false, std::memory_order_acq_rel)) {
                return;
            }
            // A second deliberate BOOT tap can explicitly restore listening.
            // A second tap is explicit manual unmute, but unattended audio
            // may never restart after a human touched this control.
            audio_operator_touched_.store(true, std::memory_order_release);
            const bool now_muted = !audio_operator_muted_.load(
                std::memory_order_acquire);
            audio_operator_muted_.store(now_muted, std::memory_order_release);
            app.SetSenseMicrophonePrivacyMuted(now_muted);
            static_cast<SenseReferenceCodec*>(GetAudioCodec())
                ->SetMicrophonePrivacyMuted(now_muted);
#ifdef CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED
            {
                std::lock_guard<std::mutex> lock(bench_gesture_mutex_);
                const bool held = bench_hold_consent_.Take(esp_timer_get_time());
                if (held && !now_muted && state == kDeviceStateIdle &&
                    bench_wifi_events_ready_.load(std::memory_order_acquire) &&
                    WifiManager::GetInstance().IsConnected())
                    static_cast<SenseReferenceCodec*>(GetAudioCodec())->GrantBenchPcmConsent();
            }
#endif
#endif
#ifdef CONFIG_DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED
            // Physical mute wins in setup audio testing too. An explicit
            // second BOOT tap can resume the original upstream test mode.
            if (state == kDeviceStateWifiConfiguring ||
                state == kDeviceStateAudioTesting) {
                if (now_muted) app.StopListening();
                else app.ToggleChatState();
                return;
            }
            if (now_muted) {
                if (state == kDeviceStateConnecting) {
                    // Cancel state now, before a blocked network open returns.
                    app.SetDeviceState(kDeviceStateIdle);
                }
                // The Sense application overlay drains any encoded Opus,
                // closes the ORIGINAL Xiaozhi audio channel and prevents
                // stale toggle/listen tasks from reopening the microphone.
                app.StopListening();
                return;
            }
            // Explicit unmute can resume one normal Xiaozhi session only.
            if (state == kDeviceStateIdle) app.ToggleChatState();
            return;
#else
            app.ToggleChatState();
#endif
        });
    }

    void StartNetwork() override {
        WifiBoard::StartNetwork();
        std::lock_guard<std::mutex> lock(network_tasks_mutex_);
#ifdef CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED
        // A real disconnect event catches WiFi flaps between FaceTask polls.
        // Failed event registration leaves the private recorder unavailable.
        static std::once_flag bench_wifi_once;
        std::call_once(bench_wifi_once, [this] {
            bench_wifi_events_ready_.store(
                esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID,
                    &DeskRobotSenseBoard::BenchWifiEvent, this) == ESP_OK,
                std::memory_order_release);
        });
#endif
        static desk_robot::Bridge robot_bridge(camera_, GetAudioCodec());
        static std::once_flag bridge_once;
        std::call_once(bridge_once, [this] {
            robot_bridge.Start();
            body_bridge_ = &robot_bridge;
            // Seed once, before the face task owns these mutable states.
            uint32_t pet_seed = 2166136261U;
            for (const unsigned char c : std::string_view(CONFIG_DESK_ROBOT_ID))
                pet_seed = (pet_seed ^ c) * 16777619U;
            face_behavior_.seed(pet_seed);
            eye_animator_.Seed(pet_seed);
        });
        // Face rendering must keep running if a physical UART reply stalls.
        // The separate poll remains read-only on the same bridge/UART owner.
        if (!face_task_ &&
            xTaskCreate(FaceTask, "stackchan_idle_face", 4096, this, 1, &face_task_) != pdPASS) {
            face_task_ = nullptr;
            ESP_LOGE("SenseBoard", "Face task unavailable; automatic listening retry unavailable");
            local_eye_display_->SetLocalStatus(desk_robot::FaceStatus::kFaceUnavailable);
        }
        robot_bridge.SetFaceConsumerAvailable(face_task_ != nullptr);
        if (!body_poll_task_ &&
            xTaskCreate(BodyPollTask, "sense_body_poll", 4096, this, 1, &body_poll_task_) != pdPASS) {
            body_poll_task_ = nullptr;
            body_face_state_.Publish({});
            ESP_LOGE("SenseBoard", "Body poll task unavailable; body status unknown");
        }
    }

    AudioCodec* GetAudioCodec() override {
        static SenseReferenceCodec audio_codec(AUDIO_INPUT_SAMPLE_RATE, AUDIO_OUTPUT_SAMPLE_RATE,
            AUDIO_I2S_SPK_GPIO_BCLK, AUDIO_I2S_SPK_GPIO_LRCK, AUDIO_I2S_SPK_GPIO_DOUT,
            AUDIO_PDM_MIC_GPIO_SCK, AUDIO_PDM_MIC_GPIO_DIN);
        return &audio_codec;
    }
    Display* GetDisplay() override { return display_; }
    Led* GetLed() override {
#ifdef CONFIG_DESK_ROBOT_RGB_HEART_ENABLED
        // Reuse Xiaozhi's existing low-brightness, audio-state-aware
        // Espressif led_strip driver. This GPIO is NEVER enabled by default:
        // shipped Sense SD J3 isolation and the external 3.3V to 5V
        // WS2812 logic buffer/power path must be qualified separately.
        static SingleLed heart(RGB_HEART_GPIO);
        return &heart;
#else
        return WifiBoard::GetLed();
#endif
    }
    Camera* GetCamera() override { return camera_; }
};

DECLARE_BOARD(DeskRobotSenseBoard);
