#pragma once

#include "sdkconfig.h"
#include <driver/gpio.h>
#include <driver/i2c_types.h>

// Candidate: Waveshare ESP32-S3-CAM-OV5640, 16 MB flash / 8 MB PSRAM.
// Stock camera/audio/CH32 mapping: pinned Xiaozhi waveshare/esp32-s3-cam.
// External OLED uses otherwise-unused LCD connector IO1/IO2; no SPI LCD attached.
#if !defined(CONFIG_USE_AUDIO_PROCESSOR) || !defined(CONFIG_USE_DEVICE_AEC) || defined(CONFIG_USE_SERVER_AEC)
#error "Device-side AEC with the physical reference is required for this candidate"
#endif
#if !defined(CONFIG_SCCB_HARDWARE_I2C_PORT1) || defined(CONFIG_SCCB_HARDWARE_I2C_PORT0) || !defined(CONFIG_SCCB_HARDWARE_I2C_DRIVER_NEW)
#error "Keep separate camera/audio I2C1 and OLED I2C0 buses"
#endif
#if !defined(CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG) || !defined(CONFIG_ESP_CONSOLE_SECONDARY_NONE) || defined(CONFIG_ESP_CONSOLE_UART_DEFAULT) || defined(CONFIG_ESP_CONSOLE_UART_CUSTOM)
#error "Use USB Serial/JTAG only: GPIO43/44 carry the body UART"
#endif

#define AUDIO_INPUT_SAMPLE_RATE 24000
#define AUDIO_OUTPUT_SAMPLE_RATE 24000
#define AUDIO_INPUT_REFERENCE true
#define AUDIO_I2S_GPIO_MCLK GPIO_NUM_10
#define AUDIO_I2S_GPIO_BCLK GPIO_NUM_11
#define AUDIO_I2S_GPIO_WS GPIO_NUM_12
#define AUDIO_I2S_GPIO_DIN GPIO_NUM_13
#define AUDIO_I2S_GPIO_DOUT GPIO_NUM_14
#define AUDIO_CODEC_PA_PIN GPIO_NUM_NC
#define AUDIO_CODEC_ES8311_ADDR ES8311_CODEC_DEFAULT_ADDR
#define AUDIO_CODEC_ES7210_ADDR ES7210_CODEC_DEFAULT_ADDR

#define BOOT_BUTTON_GPIO GPIO_NUM_0
#define CONTROL_I2C_SDA_PIN GPIO_NUM_8
#define CONTROL_I2C_SCL_PIN GPIO_NUM_7
#define CONTROL_I2C_PORT I2C_NUM_1
#define DISPLAY_SDA_PIN GPIO_NUM_1
#define DISPLAY_SCL_PIN GPIO_NUM_2
#define DISPLAY_I2C_PORT I2C_NUM_0
#define DISPLAY_WIDTH 128
#define DISPLAY_HEIGHT 64
#define DISPLAY_MIRROR_X false
#define DISPLAY_MIRROR_Y false

#define CAMERA_PIN_PWDN GPIO_NUM_NC
#define CAMERA_PIN_RESET GPIO_NUM_NC
#define CAMERA_PIN_XCLK GPIO_NUM_38
#define CAMERA_PIN_SIOD GPIO_NUM_NC
#define CAMERA_PIN_SIOC GPIO_NUM_NC
#define CAMERA_PIN_D7 GPIO_NUM_21
#define CAMERA_PIN_D6 GPIO_NUM_39
#define CAMERA_PIN_D5 GPIO_NUM_40
#define CAMERA_PIN_D4 GPIO_NUM_42
#define CAMERA_PIN_D3 GPIO_NUM_46
#define CAMERA_PIN_D2 GPIO_NUM_48
#define CAMERA_PIN_D1 GPIO_NUM_47
#define CAMERA_PIN_D0 GPIO_NUM_45
#define CAMERA_PIN_VSYNC GPIO_NUM_17
#define CAMERA_PIN_HREF GPIO_NUM_18
#define CAMERA_PIN_PCLK GPIO_NUM_41
#define CAMERA_SCCB_I2C_PORT CONTROL_I2C_PORT
#define XCLK_FREQ_HZ 20000000

#define ROBOT_UART_TX GPIO_NUM_43
#define ROBOT_UART_RX GPIO_NUM_44

static_assert(AUDIO_INPUT_REFERENCE, "AEC needs the physical playback reference");
static_assert(CAMERA_SCCB_I2C_PORT != DISPLAY_I2C_PORT,
              "OV5640 and SSD1306 can both use 0x3C: keep buses isolated");

// Keep all active peripherals distinct and off reserved S3 pins.
static_assert([] {
    constexpr int pins[] = {
        AUDIO_I2S_GPIO_MCLK,
        AUDIO_I2S_GPIO_BCLK,
        AUDIO_I2S_GPIO_WS,
        AUDIO_I2S_GPIO_DIN,
        AUDIO_I2S_GPIO_DOUT,
        BOOT_BUTTON_GPIO,
        CONTROL_I2C_SDA_PIN,
        CONTROL_I2C_SCL_PIN,
        DISPLAY_SDA_PIN,
        DISPLAY_SCL_PIN,
        CAMERA_PIN_XCLK,
        CAMERA_PIN_D7,
        CAMERA_PIN_D6,
        CAMERA_PIN_D5,
        CAMERA_PIN_D4,
        CAMERA_PIN_D3,
        CAMERA_PIN_D2,
        CAMERA_PIN_D1,
        CAMERA_PIN_D0,
        CAMERA_PIN_VSYNC,
        CAMERA_PIN_HREF,
        CAMERA_PIN_PCLK,
        ROBOT_UART_TX,
        ROBOT_UART_RX,
    };
    for (unsigned i = 0; i < sizeof(pins) / sizeof(pins[0]); ++i) {
        const int pin = pins[i];
        if (pin < 0 || pin > 48 || pin == 3 || pin == 19 || pin == 20 ||
            (pin >= 22 && pin <= 37)) {
            return false;
        }
        for (unsigned j = 0; j < i; ++j) {
            if (pin == pins[j]) return false;
        }
    }
    return true;
}(), "Head peripheral GPIO collision or reserved GPIO");
static_assert(AUDIO_CODEC_PA_PIN == GPIO_NUM_NC &&
              CAMERA_PIN_PWDN == GPIO_NUM_NC &&
              CAMERA_PIN_RESET == GPIO_NUM_NC &&
              CAMERA_PIN_SIOD == GPIO_NUM_NC &&
              CAMERA_PIN_SIOC == GPIO_NUM_NC,
              "Unused head pins must remain disconnected");
static_assert(ROBOT_UART_TX == GPIO_NUM_43 && ROBOT_UART_RX == GPIO_NUM_44,
              "Body UART mapping must match the installed bridge");
static_assert(CONTROL_I2C_PORT == I2C_NUM_1 && DISPLAY_I2C_PORT == I2C_NUM_0,
              "Keep control and OLED on separate I2C controllers");
