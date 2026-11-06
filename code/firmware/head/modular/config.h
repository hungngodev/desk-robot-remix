#pragma once
#include "sdkconfig.h"
#include <driver/gpio.h>

// With explicit SCCB pins esp32-camera chooses its bus from Kconfig, not the
// camera_config_t port field. Reserve controller 0 so the OLED can use 1.
#if !defined(CONFIG_SCCB_HARDWARE_I2C_PORT0) || defined(CONFIG_SCCB_HARDWARE_I2C_PORT1) || !defined(CONFIG_SCCB_HARDWARE_I2C_DRIVER_NEW)
#error "Modular head requires camera SCCB on I2C0 using the new I2C driver"
#endif

// Freenove FNK0085B / ESP32-S3-WROOM-1-N16R8. No microSD is used.
#define AUDIO_INPUT_SAMPLE_RATE 16000
#define AUDIO_OUTPUT_SAMPLE_RATE 24000
#define AUDIO_I2S_MIC_GPIO_WS GPIO_NUM_41
#define AUDIO_I2S_MIC_GPIO_SCK GPIO_NUM_42
#define AUDIO_I2S_MIC_GPIO_DIN GPIO_NUM_40
#define AUDIO_I2S_SPK_GPIO_DOUT GPIO_NUM_47
#define AUDIO_I2S_SPK_GPIO_BCLK GPIO_NUM_14
#define AUDIO_I2S_SPK_GPIO_LRCK GPIO_NUM_21
#define BOOT_BUTTON_GPIO GPIO_NUM_0

#define DISPLAY_SDA_PIN GPIO_NUM_38
#define DISPLAY_SCL_PIN GPIO_NUM_39
#define DISPLAY_I2C_PORT I2C_NUM_1
#define DISPLAY_WIDTH 128
#define DISPLAY_HEIGHT 64
#define DISPLAY_MIRROR_X true
#define DISPLAY_MIRROR_Y true

// Stock Freenove / ESP32-S3-EYE camera wiring, matching Xiaozhi's S3CAM target.
#define CAMERA_PIN_D0 GPIO_NUM_11
#define CAMERA_PIN_D1 GPIO_NUM_9
#define CAMERA_PIN_D2 GPIO_NUM_8
#define CAMERA_PIN_D3 GPIO_NUM_10
#define CAMERA_PIN_D4 GPIO_NUM_12
#define CAMERA_PIN_D5 GPIO_NUM_18
#define CAMERA_PIN_D6 GPIO_NUM_17
#define CAMERA_PIN_D7 GPIO_NUM_16
#define CAMERA_PIN_XCLK GPIO_NUM_15
#define CAMERA_PIN_PCLK GPIO_NUM_13
#define CAMERA_PIN_VSYNC GPIO_NUM_6
#define CAMERA_PIN_HREF GPIO_NUM_7
#define CAMERA_PIN_SIOC GPIO_NUM_5
#define CAMERA_PIN_SIOD GPIO_NUM_4
#define CAMERA_PIN_PWDN GPIO_NUM_NC
#define CAMERA_PIN_RESET GPIO_NUM_NC
#define CAMERA_SCCB_I2C_PORT I2C_NUM_0
#define XCLK_FREQ_HZ 20000000

// UART pins are shared with the common robot bridge. USB 19/20, debug 43/44,
// octal PSRAM 35/36/37 and onboard RGB GPIO48 are deliberately not assigned.
#define ROBOT_UART_TX GPIO_NUM_2
#define ROBOT_UART_RX GPIO_NUM_1
