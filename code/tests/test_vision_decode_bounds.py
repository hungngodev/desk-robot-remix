"""Physical camera JPEG bounds shared by local object and scene detectors."""

from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

import pytest
from desk_robot.vision import Detection, VisualChangeGate, YoloWorldVision, image_size
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


class FakeBox:
    def __init__(self, confidence, corners):
        self.conf = SimpleNamespace(item=lambda: confidence)
        self.xyxy = [SimpleNamespace(tolist=lambda: corners)]


class FakeBoxesModel(CountingModel):
    def __init__(self, boxes):
        super().__init__()
        self.boxes = boxes

    def predict(self, image, *, verbose, device):
        super().predict(image, verbose=verbose, device=device)
        return [SimpleNamespace(boxes=self.boxes)]


def test_yolo_disposes_untrusted_confidence_and_geometry_before_recall(tmp_path):
    weights = tmp_path / "local-model.pt"
    weights.write_bytes(b"fixture only")
    valid = FakeBox(0.92, [3, 5, 25, 30])
    invalid = [
        FakeBox(float("nan"), [3, 5, 25, 30]),
        FakeBox(float("inf"), [3, 5, 25, 30]),
        FakeBox(10**1000, [3, 5, 25, 30]),
        FakeBox(True, [3, 5, 25, 30]),
        FakeBox(0.7, [-1, 5, 25, 30]),
        FakeBox(0.7, [30, 5, 25, 30]),
        FakeBox(0.7, [3, 5, 129, 30]),
        FakeBox(0.7, [3, 5, 25, 97]),
        FakeBox(0.7, [float("nan"), 5, 25, 30]),
        FakeBox(0.7, [float("inf"), 5, 25, 30]),
        FakeBox(0.7, [3, 5, 10**1000, 30]),
        FakeBox(0.7, [3, 5, 25]),
        FakeBox(0.0, [3, 5, 25, 30]),
    ]
    detector = YoloWorldVision(weights)
    detector.model = FakeBoxesModel(invalid + [valid])
    assert detector._detect(frame(), "key") == [
        Detection("key", 0.92, (3.0, 5.0, 25.0, 30.0))
    ]
    assert detector.model.calls == 2


def test_yolo_caps_untrusted_number_of_model_boxes(tmp_path):
    weights = tmp_path / "local-model.pt"
    weights.write_bytes(b"fixture only")
    detector = YoloWorldVision(weights)
    detector.model = FakeBoxesModel([
        FakeBox(0.8, [1, 1, 10, 10]) for _ in range(200)
    ])
    detections = detector._detect(frame(), "key")
    assert len(detections) == 128
    assert all(item.label == "key" and item.confidence == 0.8 for item in detections)
