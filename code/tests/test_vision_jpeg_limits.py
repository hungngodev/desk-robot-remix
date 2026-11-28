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


def test_open_camera_jpeg_and_multimodal_prepare_close_bytes_streams(monkeypatch):
    from desk_robot import multimodal, vision
    from desk_robot.vision import _check_camera_jpeg

    vision_streams = []
    multimodal_streams = []

    def track_vision(*args):
        stream = BytesIO(*args)
        vision_streams.append(stream)
        return stream

    def track_multimodal(*args):
        stream = BytesIO(*args)
        multimodal_streams.append(stream)
        return stream

    monkeypatch.setattr(vision, "BytesIO", track_vision)
    monkeypatch.setattr(multimodal, "BytesIO", track_multimodal)

    frame = _jpeg()
    assert _check_camera_jpeg(frame, max_bytes=len(frame), decode=True) == (16, 16)
    assert len(vision_streams) == 1 and all(s.closed for s in vision_streams)

    with pytest.raises(ValueError, match="Bounded JPEG"):
        with vision._open_camera_jpeg(b"short", max_bytes=1024):
            pass
    assert len(vision_streams) == 1

    # Corrupt Huffman scan: _open_camera_jpeg must still close its BytesIO on decode failure.
    valid = BytesIO()
    Image.new("RGB", (48, 48), (10, 120, 200)).save(valid, "JPEG")
    raw = valid.getvalue()
    sos = raw.find(b"\xff\xda")
    sos_len = int.from_bytes(raw[sos + 2:sos + 4], "big")
    corrupt = raw[:sos + 2 + sos_len] + b"\xff\xc4\x00\x05\x00\xff\xd9"
    with pytest.raises(OSError):
        _check_camera_jpeg(corrupt, max_bytes=len(corrupt), decode=True)
    assert len(vision_streams) == 2 and all(s.closed for s in vision_streams)

    # multimodal._prepare: success, malformed JPEG, encoder failure, and oversized output.
    encoded, fingerprint, _ = multimodal._prepare(frame)
    assert encoded.startswith(b"\xff\xd8") and len(fingerprint) == 64 * 48
    assert len(multimodal_streams) == 2 and all(s.closed for s in multimodal_streams)

    with pytest.raises(OSError):
        multimodal._prepare(corrupt)
    assert all(s.closed for s in multimodal_streams)

    orig_save = Image.Image.save

    def failing_save(self, fp, *args, **kwargs):
        raise OSError("encode error")

    monkeypatch.setattr(Image.Image, "save", failing_save)
    with pytest.raises(OSError, match="encode error"):
        multimodal._prepare(frame)
    assert all(s.closed for s in multimodal_streams)

    def oversized_save(self, fp, *args, **kwargs):
        fp.write(b"\xff\xd8" + b"0" * 1_000_005 + b"\xff\xd9")

    monkeypatch.setattr(Image.Image, "save", oversized_save)
    with pytest.raises(ValueError, match="exceeds bounded in-memory frame"):
        multimodal._prepare(frame)
    assert all(s.closed for s in multimodal_streams)
    monkeypatch.setattr(Image.Image, "save", orig_save)
