"""Shared JPEG admission rejects invalid dimensions before raster decoding."""
import warnings
from io import BytesIO
from unittest.mock import MagicMock

import pytest
from desk_robot.vision import _open_camera_jpeg
from PIL import Image


def _jpeg() -> bytes:
    output = BytesIO()
    Image.new("RGB", (16, 16)).save(output, "JPEG")
    return output.getvalue()


@pytest.mark.parametrize("size", [(0, 16), (16, 0), (4097, 16), (16, 4097), (65535, 65535)])
def test_camera_dimension_guard_precedes_raster_decode(monkeypatch, size):
    frame = _jpeg()
    candidate = MagicMock(format="JPEG", width=size[0], height=size[1])
    candidate.__enter__.return_value = candidate
    monkeypatch.setattr(Image, "open", lambda *_: candidate)
    with pytest.raises(ValueError, match="Camera dimensions invalid"):
        with _open_camera_jpeg(frame, max_bytes=len(frame)) as image:
            image.load()
    candidate.load.assert_not_called()


def test_camera_byte_limit_precedes_decoder(monkeypatch):
    frame = _jpeg()
    decoder = MagicMock()
    monkeypatch.setattr(Image, "open", decoder)
    with pytest.raises(ValueError, match="Bounded JPEG"):
        with _open_camera_jpeg(frame, max_bytes=len(frame) - 1):
            pytest.fail("Oversized frame reached the decoder")
    decoder.assert_not_called()


def test_camera_bomb_warning_has_same_error_contract(monkeypatch):
    frame = _jpeg()
    # Use a real small JPEG and a temporarily reduced Pillow pixel budget.
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 200)
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with pytest.raises(ValueError, match="Camera dimensions invalid"):
            with _open_camera_jpeg(frame, max_bytes=len(frame)):
                pytest.fail("Decoder warning did not reject frame")
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(ValueError, match="Camera dimensions invalid"):
        with _open_camera_jpeg(frame, max_bytes=len(frame)):
            pytest.fail("Decoder error did not reject frame")


def test_corrupt_huffman_scan_passes_envelope_then_raises_oserror_on_decode():
    from desk_robot.vision import _check_camera_jpeg

    valid = BytesIO()
    Image.new("RGB", (96, 96), (120, 40, 200)).save(valid, "JPEG")
    raw = valid.getvalue()
    sos = raw.find(b"\xff\xda")
    assert sos > 0
    sos_len = int.from_bytes(raw[sos + 2:sos + 4], "big")
    corrupt = raw[:sos + 2 + sos_len] + b"\xff\xc4\x00\x05\x00\xff\xd9"
    assert corrupt.startswith(b"\xff\xd8") and corrupt.endswith(b"\xff\xd9")
    assert _check_camera_jpeg(corrupt, max_bytes=len(corrupt), decode=False) == (96, 96)
    with pytest.raises(OSError):
        _check_camera_jpeg(corrupt, max_bytes=len(corrupt), decode=True)
