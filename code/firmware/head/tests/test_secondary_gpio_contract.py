"""Compile real secondary head pin headers, including rejected mutations."""

import subprocess
from pathlib import Path

import pytest

HEAD = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("variant", ["waveshare", "modular"])
def test_secondary_gpio_contract(tmp_path, variant):
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
            ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-fsyntax-only",
             "-I", str(tmp_path), str(source)],
            capture_output=True, text=True, check=False, timeout=15,
        )

    result = compile_header(original)
    assert result.returncode == 0, result.stderr
    display = "GPIO_NUM_1" if variant == "waveshare" else "GPIO_NUM_38"
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
    for before, after, diagnostic in mutations:
        assert original.count(before) == 1
        result = compile_header(original.replace(before, after))
        assert result.returncode != 0, after
        assert diagnostic in result.stderr, result.stderr
