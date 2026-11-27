"""Compile real head pin headers, including rejected mutations."""

import subprocess
from pathlib import Path

import pytest

HEAD = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("variant", "standard"),
    [("waveshare", "c++17"), ("modular", "c++17"),
     ("sense", "c++17"), ("sense", "c++11")],
)
def test_secondary_gpio_contract(tmp_path, variant, standard):
    driver = tmp_path / "driver"
    driver.mkdir()
    (driver / "gpio.h").write_text(
        "#pragma once\nenum { GPIO_NUM_NC = -1, "
        + ", ".join(f"GPIO_NUM_{pin} = {pin}" for pin in range(49))
        + " };\n"
    )
    (driver / "i2c_types.h").write_text(
        "#pragma once\nenum { I2C_NUM_0, I2C_NUM_1 };\n"
    )
    config = ["CONFIG_SCCB_HARDWARE_I2C_DRIVER_NEW"]
    if variant == "waveshare":
        config += [
            "CONFIG_USE_AUDIO_PROCESSOR",
            "CONFIG_USE_DEVICE_AEC",
            "CONFIG_SCCB_HARDWARE_I2C_PORT1",
            "CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG",
            "CONFIG_ESP_CONSOLE_SECONDARY_NONE",
        ]
    else:
        config.append("CONFIG_SCCB_HARDWARE_I2C_PORT0")
    (tmp_path / "sdkconfig.h").write_text(
        "".join(f"#define {name} 1\n" for name in config)
    )
    original = (HEAD / variant / "config.h").read_text()
    source = tmp_path / "test.cc"

    def compile_header(text):
        (tmp_path / "config.h").write_text(text)
        source.write_text('#include "config.h"\nint main() {}\n')
        return subprocess.run(
            ["g++", f"-std={standard}", "-Wall", "-Wextra", "-Werror", "-fsyntax-only",
             "-I", str(tmp_path), str(source)],
            capture_output=True, text=True, check=False, timeout=15,
        )

    result = compile_header(original)
    assert result.returncode == 0, result.stderr
    display = {"waveshare": "GPIO_NUM_1", "modular": "GPIO_NUM_38",
               "sense": "GPIO_NUM_5"}[variant]
    uart = "GPIO_NUM_43" if variant == "waveshare" else "GPIO_NUM_2"
    display_port = "I2C_NUM_0" if variant == "waveshare" else "I2C_NUM_1"
    wrong_port = "I2C_NUM_1" if variant == "waveshare" else "I2C_NUM_0"
    mutations = [
        (f"DISPLAY_SDA_PIN {display}", "DISPLAY_SDA_PIN GPIO_NUM_0", "GPIO collision"),
        (f"DISPLAY_SDA_PIN {display}", "DISPLAY_SDA_PIN GPIO_NUM_19", "reserved GPIO"),
        ("CAMERA_PIN_PWDN GPIO_NUM_NC", "CAMERA_PIN_PWDN GPIO_NUM_0", "disconnected"),
        (f"ROBOT_UART_TX {uart}", "ROBOT_UART_TX GPIO_NUM_15" if variant == "waveshare"
         else "ROBOT_UART_TX GPIO_NUM_45", "Body UART mapping"),
        (f"DISPLAY_I2C_PORT {display_port}", f"DISPLAY_I2C_PORT {wrong_port}", "separate"),
    ]
    if variant == "sense":
        mutations += [
            ("DISPLAY_SDA_PIN GPIO_NUM_5", "DISPLAY_SDA_PIN GPIO_NUM_9", "GPIO collision"),
            ("RGB_HEART_GPIO GPIO_NUM_9", "RGB_HEART_GPIO GPIO_NUM_41", "GPIO collision"),
            ("SD_CARD_CS_GPIO GPIO_NUM_21", "SD_CARD_CS_GPIO GPIO_NUM_8", "GPIO collision"),
            ("DISPLAY_SDA_PIN GPIO_NUM_5", "DISPLAY_SDA_PIN GPIO_NUM_22", "reserved GPIO"),
            ("DISPLAY_SDA_PIN GPIO_NUM_5", "DISPLAY_SDA_PIN GPIO_NUM_46", "reserved GPIO"),
            ("BOOT_BUTTON_GPIO GPIO_NUM_0", "BOOT_BUTTON_GPIO GPIO_NUM_9", "GPIO collision"),
            ("CAMERA_PIN_D7 GPIO_NUM_48", "CAMERA_PIN_D7 GPIO_NUM_18", "GPIO collision"),
            ("CAMERA_PIN_D7 GPIO_NUM_48", "CAMERA_PIN_D7 GPIO_NUM_NC", "reserved GPIO"),
            ("CAMERA_PIN_D7 GPIO_NUM_48", "CAMERA_PIN_D7 49", "reserved GPIO"),
            # Digital I2S disable must not imply a qualified physical amp shutdown pin.
            ("AUDIO_AMP_SD_MODE_GPIO GPIO_NUM_NC", "AUDIO_AMP_SD_MODE_GPIO GPIO_NUM_44",
             "Sense amplifier has no qualified MCU shutdown connection"),
        ]
    for before, after, diagnostic in mutations:
        assert original.count(before) == 1
        result = compile_header(original.replace(before, after))
        assert result.returncode != 0, after
        assert diagnostic in result.stderr, result.stderr


def test_sense_heart_uses_reserved_gpio():
    board_source = (HEAD / "sense" / "desk_robot_sense.cc").read_text()
    assert "SingleLed heart(RGB_HEART_GPIO)" in board_source
