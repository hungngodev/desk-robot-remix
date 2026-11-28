from io import BytesIO
from random import Random

import pytest
from desk_robot.scene_motion import change_fraction, registered_scene_change_mask
from desk_robot.vision import VisualChangeGate
from PIL import Image


def _scene():
    rng = Random(1774)
    return Image.frombytes("L", (80, 64), bytes(rng.randrange(30, 220) for _ in range(80 * 64)))


def _jpeg(image):
    output = BytesIO()
    image.save(output, "JPEG", quality=100)
    return output.getvalue()


@pytest.mark.parametrize("predecoded", [False, True])
@pytest.mark.parametrize("shift", [(4, 3), (-4, 3), (4, -3), (-4, -3)])
def test_static_camera_displacement_and_independent_foreground(predecoded, shift):
    scene = _scene()
    gate = VisualChangeGate()
    dx, dy = shift
    baseline = scene.crop((8, 8, 72, 56))
    moved = scene.crop((8 + dx, 8 + dy, 72 + dx, 56 + dy))

    def observe(frame):
        jpeg = _jpeg(frame)
        return gate.observe_reduced(jpeg, frame.tobytes()) if predecoded else gate.observe(jpeg)

    assert change_fraction(baseline.tobytes(), moved.tobytes(), threshold=18) > 0.5
    assert observe(baseline) is None
    assert observe(moved) is None
    assert observe(moved) is None
    assert gate._baseline == _jpeg(moved)

    gate.reset()
    assert observe(baseline) is None
    first = moved.copy()
    first.paste(250, (24 - dx, 20 - dy, 32 - dx, 28 - dy))
    second = moved.copy()
    second.paste(250, (26 - dx, 20 - dy, 34 - dx, 28 - dy))
    assert observe(first) is None
    assert observe(second) == _jpeg(baseline)


def test_periodic_and_flat_frames_do_not_claim_registration():
    periodic = bytes([40, 100, 160, 220] * 768)
    displaced = bytes([100, 160, 220, 40] * 768)
    assert registered_scene_change_mask(periodic, displaced) is None
    assert registered_scene_change_mask(bytes([60]) * 3072, bytes([80]) * 3072) is None


def test_exposure_and_translation():
    scene = _scene()
    a = scene.crop((8, 8, 72, 56)).tobytes()
    b = scene.crop((12, 11, 76, 59)).tobytes()
    bright = bytes(value + 20 for value in b)
    assert registered_scene_change_mask(a, bright) == bytes(3072)


def test_small_residual_is_not_erased_by_registration():
    scene = _scene()
    gate = VisualChangeGate()
    baseline = scene.crop((8, 8, 72, 56))
    moved = scene.crop((12, 11, 76, 59))
    baseline_jpeg = _jpeg(baseline)
    assert gate.observe_reduced(baseline_jpeg, baseline.tobytes()) is None
    moved.paste(250, (20, 20, 24, 24))
    assert gate.observe_reduced(_jpeg(moved), moved.tobytes()) is None
    assert gate._baseline == baseline_jpeg
    moved.paste(250, (20, 20, 26, 26))
    assert gate.observe_reduced(_jpeg(moved), moved.tobytes()) is None
    assert gate.observe_reduced(_jpeg(moved), moved.tobytes()) == baseline_jpeg
