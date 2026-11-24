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



async def test_yolo_close_waits_for_native_worker_exit_and_rejects_new_detect():
    vision = YoloWorldVision(None)
    entered, release = threading.Event(), threading.Event()

    def blocked(jpeg, label):
        entered.set()
        release.wait(timeout=5)
        return [Detection(label, 1.0, (0, 0, 10, 10))]

    vision._detect = blocked
    started = asyncio.create_task(vision.detect(b"frame", "key"))
    try:
        assert await asyncio.to_thread(entered.wait, 1.0)
        started.cancel()
        with pytest.raises(asyncio.CancelledError):
            await started
        closing = asyncio.create_task(vision.close())
        await asyncio.sleep(0)
        assert not closing.done()
        with pytest.raises(RuntimeError, match="YOLO detector is closed"):
            await vision.detect(b"late frame", "candy")
        closing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing
        assert any(t.is_alive() for t in vision._worker._threads)
    finally:
        release.set()
    await asyncio.wait_for(vision.close(), timeout=2)
    assert all(not t.is_alive() for t in vision._worker._threads)
    await vision.close()


async def test_runtime_shutdown_retires_yolo_executor_and_is_repeatable():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from desk_robot.runtime import Runtime

    vision = YoloWorldVision(None)
    vision._detect = lambda jpeg, label: [
        Detection(label, 0.95, (0, 0, 10, 10)),
    ]
    assert (await vision.detect(b"frame", "key"))[0].label == "key"
    runtime = Runtime.__new__(Runtime)
    runtime.settings = SimpleNamespace(mode="simulation")
    runtime.coordinator = SimpleNamespace(
        vision=vision, close=AsyncMock(), shutdown_stop_failures={},
    )
    runtime.pet = SimpleNamespace(close=AsyncMock())
    runtime.conversation = SimpleNamespace(stop=AsyncMock())
    runtime.client = SimpleNamespace(aclose=AsyncMock())
    runtime.multimodal = None
    runtime._voice_task = None
    runtime._room_dispatch_lock = threading.Lock()
    runtime._room_dispatch_pending = None
    runtime._room_task = None
    runtime._room_stop = None

    await runtime.close()
    assert runtime._closed
    assert all(not t.is_alive() for t in vision._worker._threads)
    with pytest.raises(RuntimeError, match="YOLO detector is closed"):
        await vision.detect(b"later frame", "candy")
    await runtime.close()


async def test_truncated_camera_jpeg_is_rejected_before_model_work():
    from io import BytesIO
    from unittest.mock import AsyncMock

    from desk_robot.vision import OllamaScene, image_size
    from PIL import Image

    output = BytesIO()
    Image.new("RGB", (32, 32)).save(output, "JPEG")
    frame = output.getvalue()
    assert frame.endswith(b"\xff\xd9")
    truncated = frame[:-2]
    # Pillow can identify the format and dimensions without the end marker.
    with Image.open(BytesIO(truncated)) as image:
        assert image.size == (32, 32)
    assert image_size(frame) == (32, 32)
    client = AsyncMock()
    scene = OllamaScene(client, url="http://localhost:11434", model="local-vlm")
    with pytest.raises(ValueError, match="Bounded JPEG"):
        await scene.compare(frame, truncated)
    with pytest.raises(ValueError, match="Bounded JPEG"):
        await scene.answer("What do you see?", [truncated])
    client.post.assert_not_awaited()
    with pytest.raises(ValueError, match="Bounded JPEG"):
        image_size(truncated)
    detector = YoloWorldVision(None)
    try:
        with pytest.raises(ValueError, match="Bounded JPEG"):
            await detector.detect(truncated, "key")
        assert detector.model is None
    finally:
        await detector.close()
