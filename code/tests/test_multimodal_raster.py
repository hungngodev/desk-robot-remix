"""Preserve prepared-frame pixels while eliminating redundant raster copies."""
from io import BytesIO

import pytest
from desk_robot.multimodal import _prepare
from PIL import Image, ImageDraw, ImageOps, ImageStat


def _jpeg(mode, orientation):
    image = Image.new("RGB", (320, 240), (30, 80, 120))
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 40, 90, 100), fill=(240, 180, 15))
    draw.rectangle((180, 130, 300, 210), fill=(5, 230, 70))
    image = image.convert(mode)
    exif = image.getexif()
    exif[270] = "private fixture"
    if orientation is not None:
        exif[274] = orientation
    output = BytesIO()
    image.save(output, "JPEG", exif=exif)
    return output.getvalue()


@pytest.mark.parametrize("mode", ["RGB", "L", "CMYK"])
@pytest.mark.parametrize("orientation", [None, *range(1, 9)])
@pytest.mark.parametrize("max_side", [160, 768])
def test_prepare_preserves_normalized_pixels_and_motion(mode, orientation, max_side):
    jpeg = _jpeg(mode, orientation)
    # Reference the original copy-based pixel path, independently of worker code.
    with Image.open(BytesIO(jpeg)) as image:
        image.load()
        expected = ImageOps.exif_transpose(image).convert("RGB")
    expected.thumbnail((max_side, max_side), Image.Resampling.BILINEAR)
    gray = ImageOps.grayscale(expected).resize((64, 48))
    reference = BytesIO()
    expected.save(reference, "JPEG", quality=78, optimize=True)

    encoded, fingerprint, brightness = _prepare(jpeg, max_side)
    assert encoded == reference.getvalue()
    assert fingerprint == gray.tobytes()
    assert brightness == ImageStat.Stat(gray).mean[0]
    with Image.open(BytesIO(encoded)) as prepared:
        assert prepared.size == expected.size
        assert prepared.mode == "RGB"
        assert not prepared.getexif()


def test_prepare_does_not_copy_already_upright_rgb_raster(monkeypatch):
    jpeg = _jpeg("RGB", None)
    copies = []
    original = Image.Image.copy

    def count_copy(image):
        if image.mode == "RGB" and image.size == (320, 240):
            copies.append(image.size)
        return original(image)

    monkeypatch.setattr(Image.Image, "copy", count_copy)
    encoded, fingerprint, _ = _prepare(jpeg)
    assert encoded.startswith(b"\xff\xd8") and encoded.endswith(b"\xff\xd9")
    assert len(fingerprint) == 64 * 48
    assert not copies
