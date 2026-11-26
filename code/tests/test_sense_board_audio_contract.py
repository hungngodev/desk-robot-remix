"""Compile the real Sense board audio contract without ESP-IDF hardware."""

import shutil
import subprocess
from pathlib import Path

import pytest

CONFIG = Path(__file__).resolve().parents[1] / "firmware/head/sense/config.h"


@pytest.fixture
def compile_board(tmp_path):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("C++17 compiler unavailable")
    driver = tmp_path / "driver"
    driver.mkdir()
    pins = "\n".join(f"#define GPIO_NUM_{i} {i}" for i in range(49))
    (driver / "gpio.h").write_text(pins + "\n#define GPIO_NUM_NC -1\n")
    (driver / "i2c_types.h").write_text("#define I2C_NUM_0 0\n#define I2C_NUM_1 1\n")
    (tmp_path / "sdkconfig.h").write_text(
        "#define CONFIG_SCCB_HARDWARE_I2C_PORT0 1\n"
        "#define CONFIG_SCCB_HARDWARE_I2C_DRIVER_NEW 1\n"
    )
    source = tmp_path / "board.cc"
    source.write_text('#include "config.h"\nint main() { return 0; }\n')

    def compile_header(header: str) -> subprocess.CompletedProcess[str]:
        (tmp_path / "config.h").write_text(header)
        return subprocess.run(
            [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-fsyntax-only",
             "-I", str(tmp_path), str(source)],
            capture_output=True, text=True, timeout=30, check=False,
        )

    return compile_header


def test_selected_audio_board_compiles(compile_board):
    result = compile_board(CONFIG.read_text())
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("original", "replacement", "diagnostic"),
    [
        ("AUDIO_OUTPUT_SAMPLE_RATE 32000", "AUDIO_OUTPUT_SAMPLE_RATE 24000", "32/16 kHz"),
        ("AUDIO_INPUT_SAMPLE_RATE 16000", "AUDIO_INPUT_SAMPLE_RATE 8000", "32/16 kHz"),
        (
            "AUDIO_AMP_SD_MODE_GPIO GPIO_NUM_NC",
            "AUDIO_AMP_SD_MODE_GPIO GPIO_NUM_9",
            "no qualified MCU shutdown connection",
        ),
        (
            "AUDIO_I2S_SPK_GPIO_LRCK GPIO_NUM_7\n#define AUDIO_I2S_SPK_GPIO_DOUT GPIO_NUM_8",
            "AUDIO_I2S_SPK_GPIO_LRCK GPIO_NUM_8\n#define AUDIO_I2S_SPK_GPIO_DOUT GPIO_NUM_7",
            "GPIO4/7/8",
        ),
        (
            "AUDIO_PDM_MIC_GPIO_SCK GPIO_NUM_42\n#define AUDIO_PDM_MIC_GPIO_DIN GPIO_NUM_41",
            "AUDIO_PDM_MIC_GPIO_SCK GPIO_NUM_41\n#define AUDIO_PDM_MIC_GPIO_DIN GPIO_NUM_42",
            "GPIO42/41",
        ),
    ],
)
def test_audio_board_rejects_clock_or_pin_drift(compile_board, original, replacement, diagnostic):
    header = CONFIG.read_text()
    assert header.count(original) == 1
    result = compile_board(header.replace(original, replacement))
    assert result.returncode != 0
    assert diagnostic in result.stderr
