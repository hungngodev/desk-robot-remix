"""Voice-first, motion-aware desk camera orchestration, all offline mocks."""
import asyncio
import json
import time
from io import BytesIO
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image, ImageDraw

from desk_robot.multimodal import (
    CameraFrameHub, MultimodalOrchestrator, change_fraction,
)
from desk_robot.vision import OllamaScene


def image(color="gray", square=False):
    im = Image.new("RGB", (160, 120), color)
    if square:
        ImageDraw.Draw(im).rectangle((35, 25, 68, 58), fill=(0, 0, 0))
    out = BytesIO()
    im.save(out, "JPEG", quality=92)
    return out.getvalue()


class Head:
    def __init__(self):
        self.captures = 0
        self.commands = []

    async def snapshot(self):
        self.captures += 1
        return image(square=self.captures > 1)

    async def command(self, cmd):
        self.commands.append(cmd)


class Vision:
    def __init__(self):
        self.calls = []

    async def answer(self, question, frames):
        self.calls.append((question, frames))
        return "I can see a dark square on the table."


def config(enabled=True):
    return SimpleNamespace(
        robots=[SimpleNamespace(id="robot-01"), SimpleNamespace(id="robot-02")],
        voice_vision_tools_enabled=enabled,
        vision_model="local-vlm" if enabled else "",
    )


def test_brightness_shift_not_mistaken_for_localized_motion():
    a = bytes([90] * (64 * 48))
    b = bytes([130] * (64 * 48))
    assert change_fraction(a, b) == 0
    c = bytearray(a)
    for i in range(120, 180):
        c[i] = 0
    assert change_fraction(a, bytes(c)) > 0.01


def test_frame_hub_speech_adaptive_priority_and_identity():
    hub = CameraFrameHub(["robot-01"], idle_fps=0.3, speaking_fps=1)
    now = 100.0
    assert hub.due("robot-01", now)
    hub.offer("robot-01", image(), now, source="proactive")
    assert not hub.due("robot-01", 100.8)
    assert not hub.due("robot-01", 101.4)
    assert hub.due("robot-01", 103.4)
    hub.notify("robot-01", "human_voice", 103.4)
    assert hub.user_active("robot-01", 108)
    assert hub.due("robot-01", 103.4)
    hub.offer("robot-01", image(), 103.5, source="speech")
    assert not hub.due("robot-01", 104.1)
    assert hub.due("robot-01", 104.6)
    hub.notify("robot-01", "petting_zone", 104.7)
    assert hub.due("robot-01", 104.7)
    events = hub.recent_events("robot-01", 105)
    assert [x["kind"] for x in events] == ["human_voice", "petting_zone"]
    assert events[0]["source"] == "xiaozhi_vad"
    assert events[1]["source"] == "wroom_sensed_event"
    with pytest.raises(ValueError):
        hub.notify("robot-99", "human_voice", 110)
    with pytest.raises(ValueError):
        hub.offer("robot-01", image(), 103, source="speech")
    hub.close()
    assert not hub.frames["robot-01"]


def test_temporal_question_selects_older_and_latest_in_same_robot():
    hub = CameraFrameHub(["robot-01", "robot-02"])
    hub.offer("robot-01", image(), 10.0, source="proactive")
    hub.offer("robot-01", image(square=True), 10.5, source="sensor")
    hub.offer("robot-01", image(square=True), 11.0, source="proactive")
    hub.offer("robot-02", image("red"), 11.0, source="proactive")
    chosen = hub.selected("robot-01", "What changed just now?", 11.1)
    assert len(chosen) == 2
    # The object appeared between 10.0 and 10.5. The camera did not move
    # between 10.5 and 11.0, so comparing those latter two would be wrong.
    assert chosen[0].received_at == 10.0
    assert chosen[1].received_at == 11.0
    assert chosen[0].jpeg != chosen[1].jpeg
    assert len(hub.selected("robot-01", "What is on the desk?", 11.1)) == 1
    assert hub.selected("robot-01", "What is it?", 18.0) == []


async def test_voice_vision_tool_gets_real_authenticated_head_frames_without_actuation():
    head = Head()
    model = Vision()
    service = MultimodalOrchestrator(
        config(), {"robot-01": head, "robot-02": Head()},
        model, asyncio.Lock(),
    )
    try:
        result = await service.look("robot-01", "What is on the table?")
        assert result["frames_used"] == 1
        assert result["answer"] == "I can see a dark square on the table."
        assert result["source"] == "authenticated_xiao_camera_and_local_vlm"
        assert not result["motor_authorized"] and not result["charging_authorized"]
        assert head.captures == 1 and head.commands == []
        assert len(model.calls[0][1]) == 1
        assert model.calls[0][1][0].startswith(b"\xff\xd8")
        assert result["latest_frame_age_ms"] >= 0
        assert result["recent_sensor_events"] == []
    finally:
        await service.close()


async def test_actual_human_vad_schedules_camera_without_awaiting_jpeg():
    head = Head()
    service = MultimodalOrchestrator(
        config(), {"robot-01": head, "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    try:
        service.voice_started("robot-01")  # synchronous, urgent audio comes first
        async with asyncio.timeout(1):
            while head.captures == 0:
                await asyncio.sleep(0.01)
        assert service.hub.user_active("robot-01", time.monotonic())
        assert service.status("robot-01")["frames_in_ram"] >= 1
        assert service.status("robot-01")["motor_authorized"] is False
    finally:
        await service.close()
        assert not service.hub.frames["robot-01"]


async def test_camera_is_off_without_explicit_voice_vision_opt_in():
    head = Head()
    service = MultimodalOrchestrator(
        config(False), {"robot-01": head, "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    try:
        service.voice_started("robot-01")
        await asyncio.sleep(0)
        assert head.captures == 0
        with pytest.raises(ValueError, match="Enable"):
            await service.look("robot-01", "What is there?")
    finally:
        await service.close()


@pytest.mark.parametrize(("answer", "expected"), [
    ({"answer": "A blue cup is on the desk.", "visually_supported": True,
      "confidence": 0.93}, "A blue cup is on the desk."),
    ({"answer": "Maybe a cup.", "visually_supported": True,
      "confidence": 0.22}, "I can't tell from my camera right now."),
    ({"answer": "Unclear.", "visually_supported": False,
      "confidence": 0.9}, "I can't tell from my camera right now."),
])
async def test_local_vlm_speaks_from_visual_evidence_and_not_confidence_guess(answer, expected):
    def handler(req):
        body = json.loads(req.content)
        assert body["stream"] is False
        assert body["format"] == "json"
        assert body["messages"][0]["images"][0]
        assert "motion" not in body["messages"][0].get("tools", [])
        return httpx.Response(200, json={"message": {"content": json.dumps(answer)}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = OllamaScene(client, url="http://local:11434", model="local-vlm")
        assert await model.answer("What is there?", [image()]) == expected


async def test_vlm_two_frames_for_human_temporal_question():
    observed = []
    def handler(req):
        body = json.loads(req.content)
        observed.append(body)
        return httpx.Response(200, json={
            "message": {"content": json.dumps({
                "answer": "A small object appeared.",
                "visually_supported": True, "confidence": 0.91,
            })}
        })
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = OllamaScene(client, url="http://local:11434", model="local-vlm")
        answer = await model.answer("What just changed?", [image(), image(square=True)])
        assert answer == "A small object appeared."
        assert len(observed[0]["messages"][0]["images"]) == 2


@pytest.mark.parametrize("out", [
    {"answer": "hi", "visually_supported": 1, "confidence": 0.8},
    {"answer": "hi", "visually_supported": True, "confidence": float("nan")},
    {"answer": "x" * 401, "visually_supported": True, "confidence": 0.9},
])
async def test_vlm_rejects_invalid_or_unbounded_multimodal_result(out):
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda req: httpx.Response(
            200, json={"message": {"content": json.dumps(out)}}
        )
    )) as client:
        model = OllamaScene(client, url="http://local:11434", model="local-vlm")
        with pytest.raises(ValueError):
            await model.answer("Tell me what you see", [image()])


async def test_new_real_human_utterance_cancels_old_vlm_image_answer():
    entered = asyncio.Event()
    class SlowVision:
        async def answer(self, question, frames):
            entered.set()
            await asyncio.Event().wait()
            return "STALE visual answer"

    head = Head()
    service = MultimodalOrchestrator(
        config(), {"robot-01": head, "robot-02": Head()},
        SlowVision(), asyncio.Lock(),
    )
    try:
        task = asyncio.create_task(service.look("robot-01", "What is this?"))
        await asyncio.wait_for(entered.wait(), timeout=1)
        service.voice_started("robot-01")
        with pytest.raises(RuntimeError, match="newer speech"):
            await task
        assert not service._look_tasks
    finally:
        await service.close()


async def test_second_visual_tool_call_replaces_previous_stale_question():
    first = asyncio.Event()
    class TwoVision:
        async def answer(self, question, frames):
            if question == "What did I first show?":
                first.set()
                await asyncio.Event().wait()
            return "The newest object."

    service = MultimodalOrchestrator(
        config(), {"robot-01": Head(), "robot-02": Head()},
        TwoVision(), asyncio.Lock(),
    )
    try:
        earlier = asyncio.create_task(
            service.look("robot-01", "What did I first show?")
        )
        await asyncio.wait_for(first.wait(), timeout=1)
        latest = await service.look("robot-01", "What is there now?")
        assert latest["answer"] == "The newest object."
        with pytest.raises(RuntimeError, match="newer visual question"):
            await earlier
        assert latest["motor_authorized"] is False
    finally:
        await service.close()


async def test_speech_end_preserves_visual_evidence_and_stops_capture_task():
    head = Head()
    service = MultimodalOrchestrator(
        config(), {"robot-01": head, "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    try:
        service.voice_started("robot-01")
        async with asyncio.timeout(1):
            while not service.hub.frames["robot-01"]:
                await asyncio.sleep(0.005)
        frames = len(service.hub.frames["robot-01"])
        service.voice_ended("robot-01")
        assert not service.hub.user_active("robot-01", time.monotonic())
        await asyncio.sleep(0)
        assert len(service.hub.frames["robot-01"]) == frames
        assert service.hub.selected(
            "robot-01", "What do you see?", time.monotonic()
        )
    finally:
        await service.close()


async def test_jpeg_resize_worker_cannot_block_new_vad_on_event_loop(monkeypatch):
    import threading
    import desk_robot.multimodal as module

    entered = threading.Event()
    release = threading.Event()
    original = module._prepare

    def slow_decode(jpeg):
        entered.set()
        if not release.wait(2):
            raise AssertionError("test JPEG thread blocked")
        return original(jpeg)

    monkeypatch.setattr(module, "_prepare", slow_decode)
    service = MultimodalOrchestrator(
        config(), {"robot-01": Head(), "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    try:
        pending = asyncio.create_task(
            service.capture("robot-01", source="speech")
        )
        assert await asyncio.to_thread(entered.wait, 1)
        # This MUST run immediately while another worker decodes JPEG;
        # it only changes VAD state, never waits on a Pillow worker.
        service.voice_started("robot-02")
        assert service.hub.user_active("robot-02", time.monotonic())
        release.set()
        await asyncio.wait_for(pending, 1)
    finally:
        release.set()
        await service.close()


async def test_preprocessing_finishing_after_pause_cannot_republish_frame(monkeypatch):
    import threading
    import desk_robot.multimodal as module

    entered = threading.Event()
    release = threading.Event()
    original = module._prepare

    def slow_decode(jpeg):
        entered.set()
        if not release.wait(2):
            raise AssertionError("test JPEG thread blocked")
        return original(jpeg)

    monkeypatch.setattr(module, "_prepare", slow_decode)
    service = MultimodalOrchestrator(
        config(), {"robot-01": Head(), "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    try:
        pending = asyncio.create_task(service.offer_proactive(
            "robot-01", image(), time.monotonic()
        ))
        assert await asyncio.to_thread(entered.wait, 1)
        service.hub.clear("robot-01")
        release.set()
        with pytest.raises(RuntimeError, match="Old camera generation"):
            await pending
        assert not service.hub.frames["robot-01"]
    finally:
        release.set()
        await service.close()
