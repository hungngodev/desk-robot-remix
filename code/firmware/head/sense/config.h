#pragma once

#include <driver/gpio.h>
#include <driver/i2c_types.h>
#include "sdkconfig.h"

#if !defined(CONFIG_SCCB_HARDWARE_I2C_PORT0) || defined(CONFIG_SCCB_HARDWARE_I2C_PORT1) || !defined(CONFIG_SCCB_HARDWARE_I2C_DRIVER_NEW)
#error "Sense head requires camera SCCB on I2C0 using the new I2C driver"
#endif

// Seeed XIAO ESP32S3 Sense (8 MB flash / 8 MB octal PSRAM).
// Pin source: https://wiki.seeedstudio.com/xiao_esp32s3_pin_multiplexing/
// These connections are compile-checked, not physically qualified.
#define AUDIO_INPUT_SAMPLE_RATE 16000
// MAX98357A does not support 24 kHz LRCLK; 32 kHz retains voice bandwidth.
#define AUDIO_OUTPUT_SAMPLE_RATE 32000
#define AUDIO_PDM_MIC_GPIO_SCK GPIO_NUM_42
#define AUDIO_PDM_MIC_GPIO_DIN GPIO_NUM_41
#define AUDIO_I2S_SPK_GPIO_BCLK GPIO_NUM_4
#define AUDIO_I2S_SPK_GPIO_LRCK GPIO_NUM_7
#define AUDIO_I2S_SPK_GPIO_DOUT GPIO_NUM_8
#define BOOT_BUTTON_GPIO GPIO_NUM_0

#define DISPLAY_SDA_PIN GPIO_NUM_5
#define DISPLAY_SCL_PIN GPIO_NUM_6
#define DISPLAY_I2C_PORT I2C_NUM_1
#define DISPLAY_WIDTH 128
#define DISPLAY_HEIGHT 64
#define DISPLAY_MIRROR_X false
#define DISPLAY_MIRROR_Y false

#define CAMERA_PIN_D0 GPIO_NUM_15
#define CAMERA_PIN_D1 GPIO_NUM_17
#define CAMERA_PIN_D2 GPIO_NUM_18
#define CAMERA_PIN_D3 GPIO_NUM_16
#define CAMERA_PIN_D4 GPIO_NUM_14
#define CAMERA_PIN_D5 GPIO_NUM_12
#define CAMERA_PIN_D6 GPIO_NUM_11
#define CAMERA_PIN_D7 GPIO_NUM_48
#define CAMERA_PIN_XCLK GPIO_NUM_10
#define CAMERA_PIN_PCLK GPIO_NUM_13
#define CAMERA_PIN_VSYNC GPIO_NUM_38
#define CAMERA_PIN_HREF GPIO_NUM_47
#define CAMERA_PIN_SIOD GPIO_NUM_40
#define CAMERA_PIN_SIOC GPIO_NUM_39
#define CAMERA_PIN_PWDN GPIO_NUM_NC
#define CAMERA_PIN_RESET GPIO_NUM_NC
#define CAMERA_SCCB_I2C_PORT I2C_NUM_0
#define XCLK_FREQ_HZ 20000000

#define ROBOT_UART_TX GPIO_NUM_2
#define ROBOT_UART_RX GPIO_NUM_1
// SPI pins7/8 are reused by audio: leave the SD slot EMPTY and never initialize it.
#define SD_CARD_CS_GPIO GPIO_NUM_21
// Reserve native USB19/20, debug UART43/44, strapping3, flash/PSRAM26..37.
