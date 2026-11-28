"""Check firmware agreement for the reserved Sense GPIOs in the signal manifest."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "emit_wiring_manifest", ROOT / "code/scripts/emit_wiring_manifest.py"
)
assert SPEC is not None and SPEC.loader is not None
manifest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manifest)


@pytest.fixture
def pins_and_source():
    plan = json.loads((ROOT / "docs/hardware/full-feature-plan.json").read_text())
    head = (ROOT / "code/firmware/head/sense/config.h").read_text()
    return plan["bus"]["sense_gpio"], head


def test_head_gpio_baseline_and_continued_define(pins_and_source):
    pins, head = pins_and_source
    manifest._verify_sense_gpio(pins, head)
    head = head.replace(
        "#define RGB_HEART_GPIO GPIO_NUM_9",
        "# define\tRGB_HEART_GPIO \\\n  GPIO_NUM_9 /* reserved */",
    )
    manifest._verify_sense_gpio(pins, head)


@pytest.mark.parametrize("gpio", [8, 10])
def test_head_rgb_macro_drift(pins_and_source, gpio):
    pins, head = pins_and_source
    head = head.replace("RGB_HEART_GPIO GPIO_NUM_9", f"RGB_HEART_GPIO GPIO_NUM_{gpio}")
    with pytest.raises(ValueError, match="Firmware Sense pin drift: rgb_data"):
        manifest._verify_sense_gpio(pins, head)


@pytest.mark.parametrize("gpio", [5, 22])
def test_head_sd_cs_must_stay_fixed(pins_and_source, gpio):
    pins, head = pins_and_source
    head = head.replace("SD_CARD_CS_GPIO GPIO_NUM_21", f"SD_CARD_CS_GPIO GPIO_NUM_{gpio}")
    with pytest.raises(ValueError, match="Stock Sense pin changed: SD_CARD_CS_GPIO"):
        manifest._verify_sense_gpio(pins, head)


def test_camera_collision_with_sd_reservation(pins_and_source):
    pins, head = pins_and_source
    head = head.replace("CAMERA_PIN_D0 GPIO_NUM_15", "CAMERA_PIN_D0 GPIO_NUM_21")
    with pytest.raises(ValueError, match="collides.*SD signal"):
        manifest._verify_sense_gpio(pins, head)


def test_head_commented_pin_cannot_prove_firmware_agreement(pins_and_source):
    pins, head = pins_and_source
    head = head.replace("#define RGB_HEART_GPIO GPIO_NUM_9", "// #define RGB_HEART_GPIO GPIO_NUM_9")
    with pytest.raises(ValueError, match="Missing or duplicate firmware pin: RGB_HEART_GPIO"):
        manifest._verify_sense_gpio(pins, head)


@pytest.mark.parametrize("symbol", [
    "AUDIO_AMP_SD_MODE_GPIO", "CAMERA_PIN_PWDN", "CAMERA_PIN_RESET",
])
@pytest.mark.parametrize("replacement", ["allocated", "missing", "duplicate"])
def test_disconnected_head_control_pins(pins_and_source, symbol, replacement):
    pins, head = pins_and_source
    original = f"#define {symbol} GPIO_NUM_NC"
    changed = {
        "allocated": f"#define {symbol} GPIO_NUM_4",
        "missing": f"// {original}",
        "duplicate": f"{original}\n#define {symbol} GPIO_NUM_4",
    }[replacement]
    assert original in head
    with pytest.raises(ValueError, match=f"Sense control pin must remain disconnected: {symbol}"):
        manifest._verify_sense_gpio(pins, head.replace(original, changed))
