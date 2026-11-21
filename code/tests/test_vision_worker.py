"""Native YOLO model ownership survives cancellation of its asyncio waiter."""
import asyncio
import threading

import pytest
from desk_robot.vision import Detection, YoloWorldVision


async def test_cancelled_yolo_await_keeps_exclusive_model_until_native_exit():
    vision = YoloWorldVision(None)
    started = threading.Event()
    release = threading.Event()
    entered = []

    def blocked_detect(jpeg, label):
        entered.append(label)
        if label == "key":
            started.set()
            release.wait(timeout=5)
        return [Detection(label, 1.0, (0, 0, 10, 10))]

    vision._detect = blocked_detect
    old = asyncio.create_task(vision.detect(b"first frame", "key"))
    try:
        assert await asyncio.to_thread(started.wait, 1.0)
        old.cancel()
        with pytest.raises(asyncio.CancelledError):
            await old
        # The native worker is still running even after the awaiter is gone.
        with pytest.raises(RuntimeError, match="YOLO detector still busy"):
            await vision.detect(b"second frame", "candy")
        assert entered == ["key"]
    finally:
        release.set()
        await asyncio.sleep(0)

    # Worker completion, not asyncio cancellation, returns the model lease.
    for _ in range(100):
        try:
            result = await vision.detect(b"new frame", "candy")
            break
        except RuntimeError as exc:
            if "still busy" not in str(exc):
                raise
            await asyncio.sleep(.01)
    else:
        pytest.fail("Native YOLO worker did not release its ownership")
    assert entered == ["key", "candy"]
    assert result == [Detection("candy", 1.0, (0, 0, 10, 10))]


async def test_model_exception_releases_worker_lease():
    vision = YoloWorldVision(None)

    def fail(*args):
        raise ValueError("bad model response")

    vision._detect = fail
    with pytest.raises(ValueError, match="bad model response"):
        await vision.detect(b"frame", "key")
    vision._detect = lambda jpeg, label: [Detection(label, 1.0, (1, 2, 3, 4))]
    assert (await vision.detect(b"next frame", "candy"))[0].label == "candy"


async def test_native_visual_question_huge_confidence_fails_closed_without_crash():
    """Oversized Ollama confidence must not abort the camera question worker."""
    import json
    from io import BytesIO

    from desk_robot.vision import OllamaScene
    from PIL import Image

    jpeg = BytesIO()
    Image.new("RGB", (16, 16), (100, 100, 100)).save(jpeg, "JPEG")
    valid_frame = jpeg.getvalue()

    class Response:
        def __init__(self, confidence):
            self.confidence = confidence
        def raise_for_status(self):
            return None
        def json(self):
            return {"message": {"content": json.dumps({
                "visually_supported": True, "confidence": self.confidence,
                "answer": "A key is visible on the desk.",
            })}}

    class Client:
        confidence = 10 ** 1000
        async def post(self, *args, **kwargs):
            return Response(self.confidence)

    client = Client()
    vision = OllamaScene(client, url="http://localhost:11434", model="local-vlm")
    for confidence in (10 ** 1000, -(10 ** 1000)):
        client.confidence = confidence
        with pytest.raises(ValueError, match="Unbounded or malformed"):
            await vision.answer("What do you see?", [valid_frame])
    client.confidence = 0.91
    assert await vision.answer("What do you see?", [valid_frame]) == (
        "A key is visible on the desk."
    )


@pytest.mark.parametrize("invalid_kind", [[], ["person"], {}, {"kind": "person"}, 1, None])
async def test_scene_comparator_unhashable_model_kind_is_rejected_without_crash(invalid_kind):
    import json
    from io import BytesIO

    from desk_robot.vision import OllamaScene
    from PIL import Image

    image = BytesIO()
    Image.new("RGB", (16, 16), (100, 100, 100)).save(image, "JPEG")
    frame = image.getvalue()

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": json.dumps({
                "notable": True, "kind": client.kind,
                "description": "A person entered the scene",
                "confidence": 0.95,
            })}}

    class Client:
        kind = invalid_kind

        async def post(self, *args, **kwargs):
            return Response()

    client = Client()
    scene = OllamaScene(client, url="http://localhost:11434", model="local-vlm")
    # Model JSON data may contain a non-string kind; no observer task should
    # terminate because Python cannot hash an array or object.
    assert await scene.compare(frame, frame) is None
    client.kind = "person"
    change = await scene.compare(frame, frame)
    assert change is not None
    assert change.kind == "person"
    assert change.confidence == 0.95
