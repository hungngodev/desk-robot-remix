from io import BytesIO

import pytest
from desk_robot.multimodal import change_fraction
from desk_robot.vision import VisualChangeGate
from PIL import Image


def _jpeg(gray: bytes) -> bytes:
    output = BytesIO()
    Image.frombytes("L", (64, 48), gray).save(output, "JPEG", quality=100)
    return output.getvalue()


def _patch(gray: bytes, x: int, y: int, value: int) -> bytes:
    pixels = bytearray(gray)
    for row in range(y, y + 6):
        pixels[row * 64 + x:row * 64 + x + 5] = bytes([value]) * 5
    return bytes(pixels)


@pytest.mark.parametrize("predecoded", [False, True])
def test_disjoint_noise_cannot_confirm_a_static_scene(predecoded):
    gate = VisualChangeGate()
    background = bytes([60, 100, 140, 180] * 768)
    baseline = _jpeg(background)

    def observe(gray):
        frame = _jpeg(gray)
        return gate.observe_reduced(frame, gray) if predecoded else gate.observe(frame)

    assert observe(background) is None
    for index in range(24):
        exposure = 12 if index % 2 else -12
        flicker = bytes(value + exposure + (i % 7 - 3) for i, value in enumerate(background))
        noise = _patch(flicker, 8 if index % 2 else 40, 12, 250)
        assert change_fraction(background, noise, threshold=18) >= 0.008
        assert observe(noise) is None
    assert gate._baseline == baseline
    # A real small object with slight motion still earns a semantic comparison.
    assert observe(_patch(background, 20, 20, 0)) is None
    assert observe(_patch(background, 22, 20, 0)) == baseline
    assert observe(_patch(background, 22, 20, 0)) is None


def test_opposite_residuals_do_not_confirm_and_reset_discards_candidate():
    gate = VisualChangeGate()
    background = bytes([60, 100, 140, 180] * 768)
    baseline = _jpeg(background)
    bright = _jpeg(_patch(background, 20, 20, 250))
    dark = _jpeg(_patch(background, 20, 20, 0))
    assert gate.observe(baseline) is None
    for frame in (bright, dark) * 5:
        assert gate.observe(frame) is None
    gate.reset()
    assert gate._candidate_mask is None
    assert gate.observe(baseline) is None
    assert gate.observe(dark) is None
    assert gate.observe(dark) == baseline
