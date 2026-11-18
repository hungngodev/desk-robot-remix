// Candidate board integration: stock Waveshare CAM camera, CH32 and physical-reference
// BoxAudioCodec; existing SSD1306 and authenticated robot bridge. No new DSP code.
#include "wifi_board.h"
#include "codecs/box_audio_codec.h"
#include "display/oled_display.h"
#include "application.h"
#include "button.h"
#include "config.h"
#include "esp32_camera.h"
#include "robot_bridge.h"
#include "custom_io_expander_ch32v003.h"

#include <driver/i2c_master.h>
#include <driver/ledc.h>
#include <esp_lcd_panel_io.h>
#include <esp_lcd_panel_ops.h>
#include <esp_lcd_panel_vendor.h>

class DeskRobotWaveshareBoard : public WifiBoard {
private:
    i2c_master_bus_handle_t control_bus_ = nullptr;
    i2c_master_bus_handle_t display_bus_ = nullptr;
    esp_io_expander_handle_t io_expander_ = nullptr;
    Display* display_ = nullptr;
    Esp32Camera* camera_ = nullptr;
    Button boot_button_;

    void InitializeControlBus() {
        i2c_master_bus_config_t config = {};
        config.i2c_port = CONTROL_I2C_PORT;
        config.sda_io_num = CONTROL_I2C_SDA_PIN;
        config.scl_io_num = CONTROL_I2C_SCL_PIN;
        config.clk_source = I2C_CLK_SRC_DEFAULT;
        ESP_ERROR_CHECK(i2c_new_master_bus(&config, &control_bus_));
    }

    void InitializeExpander() {
        // Preserve the stock CH32 reset/power sequence. LCD and backlight are unused.
        ESP_ERROR_CHECK(custom_io_expander_new_i2c_ch32v003(control_bus_,
            CUSTOM_IO_EXPANDER_I2C_CH32V003_ADDRESS, &io_expander_));
        const uint32_t resets = IO_EXPANDER_PIN_NUM_0 | IO_EXPANDER_PIN_NUM_1;
        const uint32_t enables = IO_EXPANDER_PIN_NUM_4 | IO_EXPANDER_PIN_NUM_6;
        ESP_ERROR_CHECK(esp_io_expander_set_dir(io_expander_, resets | enables, IO_EXPANDER_OUTPUT));
        ESP_ERROR_CHECK(esp_io_expander_set_level(io_expander_, resets, 1));
        vTaskDelay(pdMS_TO_TICKS(10));
        ESP_ERROR_CHECK(esp_io_expander_set_level(io_expander_, resets, 0));
        vTaskDelay(pdMS_TO_TICKS(10));
        ESP_ERROR_CHECK(esp_io_expander_set_level(io_expander_, resets, 1));
        vTaskDelay(pdMS_TO_TICKS(10));
        ESP_ERROR_CHECK(esp_io_expander_set_level(io_expander_, enables, 1));
    }

    void InitializeDisplay() {
        // The OV5640 shares address 0x3C with common SSD1306 modules. Use I2C0,
        // physically separate from the onboard camera/audio/CH32 I2C1 bus.
        i2c_master_bus_config_t config = {};
        config.i2c_port = DISPLAY_I2C_PORT;
        config.sda_io_num = DISPLAY_SDA_PIN;
        config.scl_io_num = DISPLAY_SCL_PIN;
        config.clk_source = I2C_CLK_SRC_DEFAULT;
        config.glitch_ignore_cnt = 7;
        config.flags.enable_internal_pullup = true;
        ESP_ERROR_CHECK(i2c_new_master_bus(&config, &display_bus_));
        esp_lcd_panel_io_i2c_config_t io_config = {};
        io_config.dev_addr = 0x3C;
        io_config.scl_speed_hz = 400000;
        io_config.control_phase_bytes = 1;
        io_config.dc_bit_offset = 6;
        io_config.lcd_cmd_bits = 8;
        io_config.lcd_param_bits = 8;
        esp_lcd_panel_io_handle_t panel_io = nullptr;
        ESP_ERROR_CHECK(esp_lcd_new_panel_io_i2c(display_bus_, &io_config, &panel_io));
        esp_lcd_panel_dev_config_t panel_config = {};
        panel_config.reset_gpio_num = GPIO_NUM_NC;
        panel_config.bits_per_pixel = 1;
        esp_lcd_panel_ssd1306_config_t ssd1306 = {};
        ssd1306.height = DISPLAY_HEIGHT;
        panel_config.vendor_config = &ssd1306;
        esp_lcd_panel_handle_t panel = nullptr;
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
        config.pin_pwdn = CAMERA_PIN_PWDN;
        config.pin_reset = CAMERA_PIN_RESET;
        config.pin_xclk = CAMERA_PIN_XCLK;
        config.pin_sccb_sda = CAMERA_PIN_SIOD;
        config.pin_sccb_scl = CAMERA_PIN_SIOC;
        config.sccb_i2c_port = CAMERA_SCCB_I2C_PORT;
        config.pin_d0 = CAMERA_PIN_D0;
        config.pin_d1 = CAMERA_PIN_D1;
        config.pin_d2 = CAMERA_PIN_D2;
        config.pin_d3 = CAMERA_PIN_D3;
        config.pin_d4 = CAMERA_PIN_D4;
        config.pin_d5 = CAMERA_PIN_D5;
        config.pin_d6 = CAMERA_PIN_D6;
        config.pin_d7 = CAMERA_PIN_D7;
        config.pin_vsync = CAMERA_PIN_VSYNC;
        config.pin_href = CAMERA_PIN_HREF;
        config.pin_pclk = CAMERA_PIN_PCLK;
        config.xclk_freq_hz = XCLK_FREQ_HZ;
        config.ledc_timer = LEDC_TIMER_0;
        config.ledc_channel = LEDC_CHANNEL_0;
        config.pixel_format = PIXFORMAT_RGB565;
        config.frame_size = FRAMESIZE_QVGA;
        config.jpeg_quality = 12;
        config.fb_count = 2;
        config.fb_location = CAMERA_FB_IN_PSRAM;
        config.grab_mode = CAMERA_GRAB_WHEN_EMPTY;
        camera_ = new Esp32Camera(config);
    }

public:
    DeskRobotWaveshareBoard() : boot_button_(BOOT_BUTTON_GPIO) {
        InitializeControlBus();
        InitializeExpander();
        InitializeDisplay();
        InitializeCamera();
        boot_button_.OnClick([this]() {
            auto& app = Application::GetInstance();
            if (app.GetDeviceState() == kDeviceStateStarting) {
                EnterWifiConfigMode();
                return;
            }
            // Development/recovery control; not a substitute for the voice gate.
            app.ToggleChatState();
        });
    }

    void StartNetwork() override {
        WifiBoard::StartNetwork();
        static desk_robot::Bridge robot_bridge(camera_);
        static std::once_flag bridge_once;
        std::call_once(bridge_once, [] { robot_bridge.Start(); });
    }

    AudioCodec* GetAudioCodec() override {
        static BoxAudioCodec audio_codec(control_bus_, AUDIO_INPUT_SAMPLE_RATE,
            AUDIO_OUTPUT_SAMPLE_RATE, AUDIO_I2S_GPIO_MCLK, AUDIO_I2S_GPIO_BCLK,
            AUDIO_I2S_GPIO_WS, AUDIO_I2S_GPIO_DOUT, AUDIO_I2S_GPIO_DIN,
            AUDIO_CODEC_PA_PIN, AUDIO_CODEC_ES8311_ADDR, AUDIO_CODEC_ES7210_ADDR,
            AUDIO_INPUT_REFERENCE);
        return &audio_codec;
    }
    Display* GetDisplay() override { return display_; }
    Camera* GetCamera() override { return camera_; }
};

DECLARE_BOARD(DeskRobotWaveshareBoard);
