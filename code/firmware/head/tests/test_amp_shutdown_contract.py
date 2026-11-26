"""Sense has digital speaker disable, not an MCU-controlled amplifier shutdown."""

from pathlib import Path

HEAD = Path(__file__).resolve().parents[1]


def test_sense_amp_shutdown_gpio_is_unallocated():
    config = (HEAD / "sense/config.h").read_text()
    assert "#define AUDIO_AMP_SD_MODE_GPIO GPIO_NUM_NC" in config
    assert "static_assert(AUDIO_AMP_SD_MODE_GPIO == GPIO_NUM_NC," in config
