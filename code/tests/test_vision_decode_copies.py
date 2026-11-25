"""Camera preprocessing must not reopen or copy an already decoded RGB frame."""
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from desk_robot.multimodal import _prepare
from desk_robot.vision import YoloWorldVision, image_size


def _jpeg(mode: str) -> bytes:
    output = BytesIO()
    Image.new(mode, (64, 48)).save(output, "JPEG")
    return output.getvalue()


@pytest.mark.parametrize("mode", ["RGB", "L", "CMYK"])
async def test_detector_decodes_once_and_keeps_rgb_raster(monkeypatch, tmp_path, mode):
    jpeg = _jpeg(mode)
    with Image.open(BytesIO(jpeg)) as source:
        expected = source.convert("RGB").tobytes()
    original_open = Image.open
    opened = []

    def track_open(*args, **kwargs):
        image = original_open(*args, **kwargs)
        opened.append(image)
        return image

    monkeypatch.setattr(Image, "open", track_open)
    weights = tmp_path / "model.pt"
    weights.touch()
    detector = YoloWorldVision(weights)
    detector.model = Mock()
    detector.model.predict.return_value = [SimpleNamespace(boxes=[])]
    try:
        assert await detector.detect(jpeg, "key") == []
        assert len(opened) == 1
        raster = detector.model.predict.call_args.args[0]
        assert raster.mode == "RGB"
        assert raster.tobytes() == expected
        assert (raster is opened[0]) == (mode == "RGB")
    finally:
        await detector.close()


def test_image_size_opens_jpeg_once(monkeypatch):
    jpeg = _jpeg("RGB")
    opened = Mock(wraps=Image.open)
    monkeypatch.setattr(Image, "open", opened)
    assert image_size(jpeg) == (64, 48)
    assert opened.call_count == 1


def test_frame_brightness_matches_immutable_fingerprint():
    encoded, fingerprint, brightness = _prepare(_jpeg("CMYK"))
    assert type(encoded) is bytes
    assert type(fingerprint) is bytes
    assert len(fingerprint) == 64 * 48
    assert brightness == sum(fingerprint) / len(fingerprint)
