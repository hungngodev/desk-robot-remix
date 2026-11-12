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
#include "led/single_led.h"
#include "sdkconfig.h"

#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <mutex>
#include <string_view>
#include <driver/i2c_master.h>
#include <esp_lcd_panel_io.h>
#include <esp_lcd_panel_ops.h>
#include <esp_lcd_panel_vendor.h>
#include <driver/gpio.h>

class DeskRobotSenseBoard : public WifiBoard {
private:
    i2c_master_bus_handle_t display_i2c_bus_ = nullptr;
    Display* display_ = nullptr;
    Esp32Camera* camera_ = nullptr;
    Button boot_button_;
    // Pinned Stackchan-agent HSM controls OLED mood only, NEVER tracks/claw.
    stackchan::behavior::HsmBehavior face_behavior_{0x5a17};
    bool face_was_speaking_ = false;
    desk_robot::Bridge* body_bridge_ = nullptr;  // existing single UART owner
    bool body_fault_active_ = true;  // offline or unchecked body is not a healthy pet
    TaskHandle_t face_task_ = nullptr;

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

    static void FaceTask(void* context) {
        auto* board = static_cast<DeskRobotSenseBoard*>(context);
        using namespace stackchan::behavior;
        uint32_t last_body_poll_ms = 0;
        bool last_rendered_fault = false;
        bool last_was_idle = false;
        while (true) {
            const uint32_t now_ms = static_cast<uint32_t>(esp_timer_get_time() / 1000);
            // Stackchan-agent already defines kTouched. Supply the actual
            // WROOM GPIO34 touch edges via the existing head UART status path.
            // This remains independent of Mac VLM latency and never calls a
            // servo or motion tool.
            if (board->body_bridge_ && now_ms - last_body_poll_ms >= 300) {
                last_body_poll_ms = now_ms;
                const auto body = board->body_bridge_->PollInteraction();
                if (body.valid) {
                    // Dedicated head pad and verified CAP1188 zones both
                    // drive immediate local eyes, without waiting for Mac VLM.
                    // Bound a burst to protect the Stackchan event queue.
                    int real_pets = body.touch_events + body.cap_touch_events;
                    if (real_pets > 3) real_pets = 3;
                    for (int i = 0; i < real_pets; ++i) {
                        board->face_behavior_.pushEvent(
                            Event(EventType::kTouched));
                    }
                    board->body_fault_active_ = body.fault;
                } else {
                    // A missing WROOM cannot be treated as a safe idle state.
                    // Network or UART status loss never creates fake touches.
                    board->body_fault_active_ = true;
                }
            }
            const auto device_state = Application::GetInstance().GetDeviceState();
            const bool speaking = device_state == kDeviceStateSpeaking;
            if (speaking && !board->face_was_speaking_) {
                board->face_behavior_.pushEvent(Event(EventType::kSpeakRequest, ""));
            } else if (!speaking && board->face_was_speaking_) {
                board->face_behavior_.pushEvent(Event(EventType::kSpeechFinished));
            }
            board->face_was_speaking_ = speaking;
            const Observation obs{now_ms};
            const Action action = board->face_behavior_.update(obs);
            // Xiaozhi owns speaking/listening/status expressions. The reused
            // Stackchan idle picker may update the existing OLED only when
            // the device is idle; never write its motion actions to the body.
            const bool idle = device_state == kDeviceStateIdle;
            if (idle && board->display_ != nullptr) {
                // Update only on a change or return from conversation, not
                // through 10 redundant LVGL/I2C writes every second.
                if (board->body_fault_active_ != last_rendered_fault ||
                    !last_was_idle) {
                    board->display_->SetEmotion(
                        board->body_fault_active_ ? "sad" : "neutral");
                    last_rendered_fault = board->body_fault_active_;
                } else if (!board->body_fault_active_ && action.set_mood) {
                    board->display_->SetEmotion(MoodName(action.mood));
                }
            }
            last_was_idle = idle;
            vTaskDelay(pdMS_TO_TICKS(100));
        }
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
        display_ = new OledDisplay(panel_io, panel, DISPLAY_WIDTH, DISPLAY_HEIGHT,
                                   DISPLAY_MIRROR_X, DISPLAY_MIRROR_Y);
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
        // One PSRAM frame buffer limits peak RAM and camera contention until
        // real simultaneous microphone/camera stress measurements exist.
        config.pixel_format = PIXFORMAT_JPEG;
        config.frame_size = FRAMESIZE_VGA;
        config.jpeg_quality = 12;
        config.fb_count = 1;
        config.fb_location = CAMERA_FB_IN_PSRAM;
        config.grab_mode = CAMERA_GRAB_WHEN_EMPTY;
        camera_ = new Esp32Camera(config);
    }

public:
    DeskRobotSenseBoard() : boot_button_(BOOT_BUTTON_GPIO) {
        // Keep the unused SD device deselected before driving its shared SPI pins.
        // No card may be inserted while GPIO7/8 are used for amplifier clocks/data.
        ESP_ERROR_CHECK(gpio_set_direction(SD_CARD_CS_GPIO, GPIO_MODE_OUTPUT));
        ESP_ERROR_CHECK(gpio_set_level(SD_CARD_CS_GPIO, 1));
        InitializeDisplay();
        InitializeCamera();
        boot_button_.OnClick([this]() {
            auto& app = Application::GetInstance();
            if (app.GetDeviceState() == kDeviceStateStarting) {
                EnterWifiConfigMode();
                return;
            }
            app.ToggleChatState();
        });
    }

    void StartNetwork() override {
        WifiBoard::StartNetwork();
        static desk_robot::Bridge robot_bridge(camera_);
        static std::once_flag bridge_once;
        std::call_once(bridge_once, [] { robot_bridge.Start(); });
        body_bridge_ = &robot_bridge;
        // Each configured robot ID seeds Stackchan's EXISTING weighted idle
        // picker independently. Five copies need not blink/smile in sync.
        uint32_t pet_seed = 2166136261U;
        for (const unsigned char c : std::string_view(CONFIG_DESK_ROBOT_ID))
            pet_seed = (pet_seed ^ c) * 16777619U;
        face_behavior_.seed(pet_seed);
        // One local OLED mood task; no new speech stack, camera task or motor
        // service. Keep idle expressions out of Xiaozhi active voice UI.
        if (!face_task_) {
            xTaskCreate(FaceTask, "stackchan_idle_face", 4096, this, 1, &face_task_);
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
        static SingleLed heart(GPIO_NUM_9);
        return &heart;
#else
        return WifiBoard::GetLed();
#endif
    }
    Camera* GetCamera() override { return camera_; }
};

DECLARE_BOARD(DeskRobotSenseBoard);
