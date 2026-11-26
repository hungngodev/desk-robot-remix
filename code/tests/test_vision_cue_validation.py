"""Reject malformed visual cues before publishing model or detector evidence."""
import json
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from desk_robot.vision import OllamaScene, YoloWorldVision, image_size
from PIL import Image


@pytest.fixture
def frame():
    output = BytesIO()
    image = Image.new("RGB", (16, 16), (100, 100, 100))
    image.paste((220, 220, 220), (8, 0, 16, 16))
    image.save(output, "JPEG")
    return output.getvalue()


def cyclic_list():
    result = []
    result.append(result)
    return result


@pytest.mark.parametrize("label", [[], {"label": ["key"]}, "key\ud800", cyclic_list()])
async def test_detector_rejects_malformed_label_before_worker(frame, label):
    detector = YoloWorldVision(None)
    detector._detect = Mock()
    try:
        with pytest.raises(ValueError, match="Invalid detector label"):
            await detector.detect(frame, label)
        detector._detect.assert_not_called()
    finally:
        await detector.close()


@pytest.mark.parametrize("body", [
    [], {"message": []}, {"message": {"content": {"nested": []}}},
    {"message": {"content": cyclic_list()}}, {"message": {"content": "{"}},
    {"message": {"content": "[" * 2000 + "]" * 2000}},
])
async def test_model_rejects_malformed_envelopes(frame, body):
    response = Mock()
    response.json.return_value = body
    client = AsyncMock()
    client.post.return_value = response
    scene = OllamaScene(client, url="http://localhost:11434", model="local-vlm")
    assert await scene.compare(frame, frame) is None
    with pytest.raises(ValueError, match="Invalid visual model answer"):
        await scene.answer("What do you see?", [frame])


@pytest.mark.parametrize("text", ["A key \ud800 is visible", ["A key"], {"nested": ["key"]}])
async def test_model_rejects_malformed_text_and_recovers(frame, text):
    response = Mock()
    client = AsyncMock()
    client.post.return_value = response
    scene = OllamaScene(client, url="http://localhost:11434", model="local-vlm")

    def set_text(value):
        response.json.return_value = {"message": {"content": json.dumps({
            "notable": True, "kind": "key", "description": value,
            "visually_supported": True, "answer": value, "confidence": 0.95,
        })}}

    set_text(text)
    assert await scene.compare(frame, frame) is None
    with pytest.raises(ValueError, match="Unbounded or malformed"):
        await scene.answer("What do you see?", [frame])
    set_text("Một chiếc chìa khóa 🔑")
    assert (await scene.compare(frame, frame)).description == "Một chiếc chìa khóa 🔑"
    assert await scene.answer("What do you see?", [frame]) == "Một chiếc chìa khóa 🔑"


async def test_surrogate_question_never_reaches_model(frame):
    client = AsyncMock()
    scene = OllamaScene(client, url="http://localhost:11434", model="local-vlm")
    with pytest.raises(ValueError, match="Real bounded camera frames"):
        await scene.answer("What is \udfff?", [frame])
    client.post.assert_not_awaited()


@pytest.mark.parametrize("corners", [(0, 0, float("nan"), 10), (0, 0, [5], 10)])
async def test_malformed_native_box_cannot_become_detection(frame, tmp_path, corners):
    weights = tmp_path / "weights.pt"
    weights.touch()
    detector = YoloWorldVision(weights)
    detector.model = Mock()
    box = SimpleNamespace(conf=Mock(), xyxy=[Mock()])
    box.conf.item.return_value = 0.95
    box.xyxy[0].tolist.return_value = corners
    detector.model.predict.return_value = [SimpleNamespace(boxes=[box])]
    try:
        with pytest.raises(ValueError, match="Invalid native detection geometry"):
            await detector.detect(frame, "key")
    finally:
        await detector.close()


def test_negative_decoded_dimensions_are_rejected(frame, monkeypatch):
    candidate = Mock(format="JPEG", width=-1, height=16)
    context = Mock()
    context.__enter__ = Mock(return_value=candidate)
    context.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(Image, "open", Mock(return_value=context))
    with pytest.raises(ValueError, match="Camera dimensions invalid"):
        image_size(frame)
    candidate.verify.assert_not_called()


def test_visual_reduction_rejects_truncated_jpeg_before_open(frame, monkeypatch):
    from desk_robot.vision import VisualChangeGate

    opener = Mock(wraps=Image.open)
    monkeypatch.setattr(Image, "open", opener)
    gate = VisualChangeGate()
    with pytest.raises(ValueError, match="Bounded JPEG"):
        gate.observe(frame[:-2])
    opener.assert_not_called()
    assert gate._baseline is None
    assert gate._pixel_baseline is None
    assert gate.observe(frame) is None
    assert gate._baseline == frame
    assert len(gate._pixel_baseline) == 64 * 48
