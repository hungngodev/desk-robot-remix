"""Physical camera JPEG bounds shared by local object and scene detectors."""

from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

import pytest
from desk_robot.vision import VisualChangeGate, YoloWorldVision, image_size
from PIL import Image


def frame() -> bytes:
    picture = Image.new("RGB", (128, 96), "white")
    out = BytesIO()
    picture.save(out, "JPEG")
    return out.getvalue()


def overlarge_header() -> bytes:
    result = bytearray(frame())
    sof = result.find(bytes([255, 192]))
    assert sof > 0
    result[sof + 5:sof + 9] = (5000).to_bytes(2, "big") * 2
    return bytes(result)


class CountingModel:
    def __init__(self):
        self.calls = 0

    def set_classes(self, classes):
        assert classes == ["key"]
        self.calls += 1

    def predict(self, image, *, verbose, device):
        assert image.size == (128, 96)
        assert image.mode == "RGB"
        assert verbose is False and device == "cpu"
        self.calls += 1
        return [SimpleNamespace(boxes=[])]


@pytest.mark.parametrize("bad", [
    b"not a jpeg",
    bytes([255, 216]) + b"forged jpeg bytes",
    b"z" * 4_000_001,
    overlarge_header(),
])
def test_yolo_rejects_unbounded_or_corrupt_camera_before_model(bad, tmp_path):
    weights = tmp_path / "local-model.pt"
    weights.write_bytes(b"fixture only")
    detector = YoloWorldVision(weights)
    detector.model = CountingModel()
    with pytest.raises((ValueError, OSError)):
        detector._detect(bad, "key")
    assert detector.model.calls == 0


def test_yolo_still_accepts_bounded_real_jpeg_without_model_download(tmp_path):
    weights = tmp_path / "local-model.pt"
    weights.write_bytes(b"fixture only")
    detector = YoloWorldVision(weights)
    detector.model = CountingModel()
    assert detector._detect(frame(), "key") == []
    assert detector.model.calls == 2
    assert image_size(frame()) == (128, 96)


def test_camera_size_helper_rejects_oversized_declared_raster():
    with pytest.raises(ValueError, match="Camera dimensions invalid"):
        image_size(overlarge_header())


def test_predecoded_visual_gate_cannot_store_malformed_jpeg_baseline():
    gate = VisualChangeGate()
    pixels = bytes(64 * 48)
    with pytest.raises(ValueError, match="Invalid camera JPEG baseline"):
        gate.observe_reduced(b"forged frame", pixels)
    assert gate._baseline is None
    assert gate._pixel_baseline is None
    assert gate._hits == 0
    assert gate.observe_reduced(frame(), pixels) is None
    assert gate._baseline == frame()
