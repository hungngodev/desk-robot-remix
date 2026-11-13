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
    CameraFrameHub, MultimodalOrchestrator, _prepare, change_fraction,
)
from desk_robot.vision import OllamaScene


def image(color="gray", square=False):
    im = Image.new("RGB", (160, 120), color)
    if square:
        ImageDraw.Draw(im).rectangle((35, 25, 68, 58), fill=(0, 0, 0))
    out = BytesIO()
    im.save(out, "JPEG", quality=92)
    return out.getvalue()


def test_oversized_jpeg_header_rejected_before_pixel_decompression():
    """A JPEG may advertise huge dimensions in a tiny source byte stream."""
    frame = bytearray(image())
    sof = frame.find(b"\xff\xc0")
    assert sof > 0  # PIL's default generated RGB JPEG is baseline SOF0.
    frame[sof + 5:sof + 9] = (5000).to_bytes(2, "big") * 2
    with pytest.raises(ValueError, match="Camera dimensions invalid"):
        _prepare(bytes(frame))


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


def test_all_new_physical_interactions_trigger_camera_without_extra_sensor_drivers():
    hub = CameraFrameHub(["robot-01", "robot-02"], idle_fps=0.3)
    hub.offer("robot-01", image(), 100.0, source="proactive")
    hub.offer("robot-02", image(), 100.0, source="proactive")
    assert not hub.due("robot-01", 100.2)
    for kind in ("paw_contact", "ambient_shift", "nfc_tag"):
        hub.notify("robot-01", kind, 100.25)
    assert hub.due("robot-01", 100.3)
    assert not hub.due("robot-02", 100.3)
    assert [x["kind"] for x in hub.recent_events("robot-01", 100.3)] == [
        "paw_contact", "ambient_shift", "nfc_tag",
    ]
    assert hub.recent_events("robot-02", 100.3) == []


def test_brightness_shift_not_mistaken_for_localized_motion():
    a = bytes([90] * (64 * 48))
    b = bytes([130] * (64 * 48))
    assert change_fraction(a, b) == 0
    c = bytearray(a)
    for i in range(120, 180):
        c[i] = 0
    assert change_fraction(a, bytes(c)) > 0.01


@pytest.mark.parametrize("cancel", [False, True])
async def test_direct_visual_request_reserves_fleet_vlm_and_camera_until_finished(cancel):
    """No new speculative JPEG/VLM may overtake the entire human look."""
    class HeldHead(Head):
        def __init__(self):
            super().__init__()
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def snapshot(self):
            self.captures += 1
            self.entered.set()
            await self.release.wait()
            return image()

    head, scene = HeldHead(), Vision()
    visual = MultimodalOrchestrator(
        config(), {"robot-01": head, "robot-02": Head()},
        scene, asyncio.Lock(),
    )
    reservation = []
    visual.begin_direct_vision = lambda: reservation.append("begin")
    visual.end_direct_vision = lambda: reservation.append("end")
    try:
        task = asyncio.create_task(
            visual.look("robot-01", "What is on the desk?")
        )
        await asyncio.wait_for(head.entered.wait(), timeout=1)
        assert reservation == ["begin"]
        # A new optional pet sample must fail BEFORE acquiring the same
        # XIAO camera lock, instead of queuing behind the direct question.
        with pytest.raises(RuntimeError, match="Explicit human look"):
            await asyncio.wait_for(
                visual.capture("robot-01", source="proactive"), timeout=.5
            )
        assert head.captures == 1
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            head.release.set()
            result = await asyncio.wait_for(task, timeout=2)
            assert result["frames_used"] == 1
            assert len(scene.calls) == 1
        assert reservation == ["begin", "end"]
        assert not visual._look_tasks
    finally:
        head.release.set()
        await visual.close()


async def test_sensor_burst_uses_existing_camera_owner_and_coalesces_requests():
    heads = {"robot-01": Head(), "robot-02": Head()}
    visual = MultimodalOrchestrator(config(), heads, Vision(), asyncio.Lock())
    try:
        for kind in ("paw_contact", "ambient_shift", "nfc_tag", "petting_zone"):
            visual.sensor_event("robot-01", kind)
        async with asyncio.timeout(2):
            while not visual.hub.frames["robot-01"]:
                await asyncio.sleep(0.01)
        assert heads["robot-01"].captures == 1
        assert heads["robot-02"].captures == 0
        assert visual.hub.frames["robot-01"][-1].source == "sensor"
        assert visual._metrics["robot-01"]["camera_successes"] == 1
        assert len(visual.hub.recent_events("robot-01", time.monotonic())) == 4
        # A second burst during the 800ms budget cannot allocate more JPEGs.
        visual.sensor_event("robot-01", "nfc_tag")
        await asyncio.sleep(0.02)
        assert heads["robot-01"].captures == 1
    finally:
        await visual.close()


async def test_sensor_two_frame_burst_never_blocks_human_speech_priority():
    heads = {"robot-01": Head(), "robot-02": Head()}
    visual = MultimodalOrchestrator(
        config(enabled=False), heads, Vision(), asyncio.Lock()
    )
    try:
        visual.sensor_event("robot-01", "petting_zone")
        async with asyncio.timeout(2):
            while heads["robot-01"].captures < 1:
                await asyncio.sleep(.01)
        # A real VAD begins during the deliberately short second-frame gap.
        visual.voice_started("robot-01")
        await asyncio.sleep(.55)
        assert heads["robot-01"].captures == 1
        assert visual.hub.user_active("robot-01", time.monotonic())
        visual.voice_ended("robot-01")
    finally:
        await visual.close()


async def test_one_human_vad_preempts_all_five_pet_optional_camera_captures():
    class SlowHead(Head):
        def __init__(self):
            super().__init__()
            self.started = asyncio.Event()
            self.cancelled = False

        async def snapshot(self):
            self.captures += 1
            self.started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise

    first, second = SlowHead(), SlowHead()
    visual = MultimodalOrchestrator(
        config(enabled=False),
        {"robot-01": first, "robot-02": second},
        Vision(), asyncio.Lock(),
    )
    task = asyncio.create_task(
        visual.capture("robot-02", source="proactive")
    )
    try:
        await asyncio.wait_for(second.started.wait(), timeout=1)
        visual.voice_started("robot-01")
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
        assert second.cancelled
        visual.sensor_event("robot-02", "petting_zone")
        await asyncio.sleep(.02)
        assert second.captures == 1
        assert visual.status("robot-02")["software_timings"]["sensor_deferred_human"] == 1
        assert not visual.hub.frames["robot-02"]
        assert visual.hub.user_active("robot-01", time.monotonic())
        visual.voice_ended("robot-01")
    finally:
        await visual.close()


async def test_other_pets_sensor_bursts_yield_to_one_fleet_human_turn():
    heads = {"robot-01": Head(), "robot-02": Head()}
    visual = MultimodalOrchestrator(
        config(enabled=False), heads, Vision(), asyncio.Lock()
    )
    try:
        visual.sensor_event("robot-02", "nfc_tag")
        async with asyncio.timeout(2):
            while heads["robot-02"].captures < 1:
                await asyncio.sleep(.01)
        visual.voice_started("robot-01")
        await asyncio.sleep(.55)
        assert heads["robot-02"].captures == 1
        assert visual.hub.user_active("robot-01", time.monotonic())
        assert not visual.hub.user_active("robot-02", time.monotonic())
        visual.voice_ended("robot-01")
    finally:
        await visual.close()


async def test_human_voice_preempts_only_the_background_snapshot():
    class SlowHead(Head):
        def __init__(self):
            super().__init__()
            self.started = asyncio.Event()
            self.cancelled = False

        async def snapshot(self):
            self.captures += 1
            if self.captures == 1:
                self.started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.cancelled = True
                    raise
            return image(square=True)

    head = SlowHead()
    visual = MultimodalOrchestrator(
        config(enabled=False), {"robot-01": head, "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    pending = asyncio.create_task(visual.capture("robot-01", source="proactive"))
    try:
        await asyncio.wait_for(head.started.wait(), timeout=1)
        visual.voice_started("robot-01")
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(pending, timeout=1)
        assert head.cancelled
        assert not visual.hub.frames["robot-01"]
        assert visual.hub.user_active("robot-01", time.monotonic())
        visual.voice_ended("robot-01")
        evidence = await visual.capture("robot-01", source="voice_question")
        assert evidence.source == "voice_question"
        assert head.captures == 2
    finally:
        await visual.close()


async def test_direct_visual_question_preempts_background_camera_request():
    class SlowHead(Head):
        def __init__(self):
            super().__init__()
            self.started = asyncio.Event()
            self.cancelled = False

        async def snapshot(self):
            self.captures += 1
            if self.captures == 1:
                self.started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.cancelled = True
                    raise
            return image(square=True)

    head = SlowHead()
    visual = MultimodalOrchestrator(
        config(enabled=True), {"robot-01": head, "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    pending = asyncio.create_task(visual.capture("robot-01", source="proactive"))
    try:
        await asyncio.wait_for(head.started.wait(), timeout=1)
        response = await asyncio.wait_for(
            visual.look("robot-01", "What object is now visible?"), timeout=3
        )
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert head.cancelled
        assert visual.status("robot-01")["software_timings"]["proactive_camera_preemptions"] == 1
        assert response["source"] == "authenticated_xiao_camera_and_local_vlm"
        assert response["frames_used"] == 1
        assert head.captures == 2
    finally:
        await visual.close()


async def test_direct_visual_question_preempts_busy_optional_model_without_extra_owner():
    lock = asyncio.Lock()
    entered = asyncio.Event()

    async def slow_speculation():
        async with lock:
            entered.set()
            await asyncio.Event().wait()

    pending = asyncio.create_task(slow_speculation())
    visual = MultimodalOrchestrator(
        config(enabled=True),
        {"robot-01": Head(), "robot-02": Head()},
        Vision(), lock,
    )
    visual.preempt_background_vision = pending.cancel
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        answer = await asyncio.wait_for(
            visual.look("robot-01", "What is on the table?"), timeout=2
        )
        assert answer["frames_used"] == 1
        assert answer["motor_authorized"] is False
        assert pending.cancelled()
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        await visual.close()


async def test_sensor_two_frame_burst_is_bounded_and_camera_serial():
    head = Head()
    visual = MultimodalOrchestrator(
        config(enabled=False),
        {"robot-01": head, "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    try:
        visual.sensor_event("robot-01", "paw_contact")
        assert visual.sensor_burst_pending("robot-01")
        assert not visual.sensor_burst_pending("robot-02")
        async with asyncio.timeout(3):
            while len(visual.hub.frames["robot-01"]) != 2:
                await asyncio.sleep(.01)
        async with asyncio.timeout(1):
            while visual.sensor_burst_pending("robot-01"):
                await asyncio.sleep(.01)
        frames = list(visual.hub.frames["robot-01"])
        assert frames[0].source == frames[1].source == "sensor"
        assert frames[0].trigger_kind == frames[1].trigger_kind == "paw_contact"
        timeline = visual.hub.interaction_timeline("robot-01", time.monotonic())
        camera = [cue for cue in timeline if cue["channel"] == "camera"]
        assert len(camera) == 2
        assert all(cue["trigger_kind"] == "paw_contact" for cue in camera)
        assert all(cue["exposure_timestamp_verified"] is False for cue in camera)
        assert frames[0].received_at < frames[1].received_at
        assert head.captures == 2
        assert visual._metrics["robot-01"]["camera_successes"] == 2
        stats = visual.status("robot-01")["software_timings"]
        assert stats["sensor_triggers"] == 1
        assert stats["sensor_bursts"] == 1
        assert stats["sensor_followup_frames"] == 1
        assert isinstance(stats["sensor_trigger_to_first_jpeg_last_ms"], int)
        assert stats["sensor_trigger_to_first_jpeg_last_ms"] >= 0
        assert head.captures <= 2
    finally:
        await visual.close()


async def test_immediate_new_speech_after_end_replaces_cancelling_camera_worker():
    visual = MultimodalOrchestrator(
        config(enabled=True),
        {"robot-01": Head(), "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    try:
        visual.voice_started("robot-01")
        first = visual._capture_tasks["robot-01"]
        visual.voice_ended("robot-01")
        assert first.cancelling()
        visual.voice_started("robot-01")  # no event-loop yield between edges
        second = visual._capture_tasks["robot-01"]
        assert second is not first
        async with asyncio.timeout(2):
            while not visual.hub.frames["robot-01"]:
                await asyncio.sleep(0.01)
        assert visual.hub.frames["robot-01"][-1].source == "speech"
        assert visual.hub.user_active("robot-01", time.monotonic())
        visual.voice_ended("robot-01")
    finally:
        await visual.close()


async def test_human_vad_cancels_pending_sensor_camera_before_speech_frames():
    class BlockedFirstCamera(Head):
        def __init__(self):
            super().__init__()
            self.entered = asyncio.Event()
            self.sensor_cancelled = False

        async def snapshot(self):
            self.captures += 1
            if self.captures == 1:
                self.entered.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.sensor_cancelled = True
                    raise
            return image(square=True)

    first = BlockedFirstCamera()
    visual = MultimodalOrchestrator(
        config(enabled=True), {"robot-01": first, "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    try:
        visual.sensor_event("robot-01", "paw_contact")
        await asyncio.wait_for(first.entered.wait(), timeout=1)
        visual.voice_started("robot-01")
        async with asyncio.timeout(2):
            while (first.captures < 2
                   or not visual.hub.frames["robot-01"]):
                await asyncio.sleep(0.01)
        assert first.sensor_cancelled
        assert visual.hub.frames["robot-01"][-1].source == "speech"
        assert visual.hub.user_active("robot-01", time.monotonic())
        visual.voice_ended("robot-01")
    finally:
        await visual.close()


def test_sensor_camera_trigger_cannot_be_forged_on_voice_or_idle_capture():
    hub = CameraFrameHub(["robot-01"])
    prepared = _prepare(image())
    with pytest.raises(ValueError, match="Only a real sensor burst"):
        hub.offer_prepared(
            "robot-01", prepared, 100.0,
            source="speech", trigger_kind="touch_tap",
        )
    with pytest.raises(ValueError, match="Only a real sensor burst"):
        hub.offer_prepared(
            "robot-01", prepared, 100.0,
            source="sensor", trigger_kind="nonexistent_vision",
        )


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


def test_speech_floor_requires_real_end_not_a_seven_second_guess():
    hub = CameraFrameHub(["robot-01", "robot-02"])
    hub.notify("robot-01", "human_voice", 100.0)
    # Long human questions must never free the spontaneous speaker floor.
    assert hub.user_active("robot-01", 108.0)
    assert hub.user_active("robot-01", 170.0)
    assert not hub.user_active("robot-02", 170.0)
    hub.speech_ended("robot-01", 170.0)
    assert not hub.user_active("robot-01", 170.0)
    hub.notify("robot-01", "human_voice", 180.0)
    hub.clear("robot-01")  # Explicit disconnect/operator reset is also release.
    assert not hub.user_active("robot-01", 180.1)


def test_aec_barge_has_finite_lease_but_never_shortens_explicit_vad():
    hub = CameraFrameHub(["robot-01"])
    hub.barge_in("robot-01", 100.0)
    assert hub.user_active("robot-01", 106.9)
    assert not hub.user_active("robot-01", 107.0)
    hub.notify("robot-01", "human_voice", 108.0)
    hub.barge_in("robot-01", 110.0)
    assert hub.user_active("robot-01", 300.0)
    hub.speech_ended("robot-01", 301.0)
    assert not hub.user_active("robot-01", 301.0)


def test_authenticated_snapshot_reconciles_missed_vad_without_losing_aec_hold():
    hub = CameraFrameHub(["robot-01", "robot-02"])
    hub.notify("robot-01", "human_voice", 100.0)
    hub.barge_in("robot-02", 101.0)
    hub.reconcile_speech_snapshot(frozenset({"robot-01"}), 103.0)
    assert hub.user_active("robot-01", 300.0)
    assert hub.user_active("robot-02", 107.0)
    hub.reconcile_speech_snapshot(frozenset(), 104.0)
    assert not hub.user_active("robot-01", 105.0)
    assert hub.user_active("robot-02", 107.0)
    assert not hub.user_active("robot-02", 108.0)


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
        timing = service.status("robot-01")["software_timings"]
        assert timing["camera_requests"] == 1
        assert timing["camera_successes"] == 1
        assert timing["visual_questions"] == 1
        assert timing["visual_answers"] == 1
        assert timing["camera_latency_last_ms"] >= 0
        assert timing["model_latency_last_ms"] >= 0
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


async def test_visual_question_uses_current_spoken_turn_not_recent_idle_photo():
    head = Head()
    service = MultimodalOrchestrator(
        config(), {"robot-01": head, "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )

    async def paused_automatic_speech_camera(_robot_id):
        await asyncio.Event().wait()

    # Prevent the background VAD sampler from being the source of this frame;
    # only the user's explicit visual tool may request a new one here.
    service._speech_frames = paused_automatic_speech_camera
    try:
        previous_idle_at = time.monotonic()
        service.hub.offer(
            "robot-01", image(), previous_idle_at, source="proactive"
        )
        service.voice_started("robot-01")
        assert previous_idle_at < service._voice_turn_at["robot-01"]
        response = await service.look("robot-01", "What can you see now?")
        assert head.captures == 1
        assert response["robot_id"] == "robot-01"
        assert service.hub.frames["robot-01"][-1].received_at >= (
            service._voice_turn_at["robot-01"]
        )
        service.voice_ended("robot-01")
    finally:
        await service.close()


async def test_fresh_frame_from_current_spoken_turn_is_reused_without_duplication():
    head = Head()
    service = MultimodalOrchestrator(
        config(), {"robot-01": head, "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )

    async def paused_automatic_speech_camera(_robot_id):
        await asyncio.Event().wait()

    service._speech_frames = paused_automatic_speech_camera
    try:
        service.voice_started("robot-01")
        service.hub.offer(
            "robot-01", image(), time.monotonic(), source="speech"
        )
        response = await service.look("robot-01", "What is on the table?")
        assert head.captures == 0
        assert response["frames_used"] == 1
        service.voice_ended("robot-01")
    finally:
        await service.close()


async def test_real_vad_during_jpeg_cpu_prepare_suppresses_late_idle_frame(monkeypatch):
    import threading
    import desk_robot.multimodal as media

    entered = threading.Event()
    release = threading.Event()
    real_prepare = media._prepare

    def slow_prepare(jpeg):
        entered.set()
        release.wait(timeout=2)
        return real_prepare(jpeg)

    monkeypatch.setattr(media, "_prepare", slow_prepare)
    service = MultimodalOrchestrator(
        config(enabled=False),
        {"robot-01": Head(), "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    task = asyncio.create_task(
        service.capture("robot-02", source="proactive")
    )
    try:
        assert await asyncio.wait_for(
            asyncio.to_thread(entered.wait, 0.8), timeout=1
        )
        service.voice_started("robot-01")
        release.set()
        with pytest.raises(RuntimeError, match="superseded"):
            await asyncio.wait_for(task, timeout=1)
        assert not service.hub.frames["robot-02"]
        assert service.hub.user_active("robot-01", time.monotonic())
        service.voice_ended("robot-01")
    finally:
        release.set()
        await service.close()


async def test_prepare_from_external_pet_cannot_add_frame_during_human_voice(monkeypatch):
    import threading
    import desk_robot.multimodal as media

    entered = threading.Event()
    release = threading.Event()
    real_prepare = media._prepare

    def slow_prepare(jpeg):
        entered.set()
        release.wait(timeout=2)
        return real_prepare(jpeg)

    monkeypatch.setattr(media, "_prepare", slow_prepare)
    service = MultimodalOrchestrator(
        config(enabled=False),
        {"robot-01": Head(), "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    task = asyncio.create_task(
        service.offer_proactive("robot-02", image(), time.monotonic())
    )
    try:
        assert await asyncio.wait_for(
            asyncio.to_thread(entered.wait, 0.8), timeout=1
        )
        service.voice_started("robot-01")
        release.set()
        await asyncio.wait_for(task, timeout=1)
        assert not service.hub.frames["robot-02"]
        assert service.hub.user_active("robot-01", time.monotonic())
        service.voice_ended("robot-01")
    finally:
        release.set()
        await service.close()


async def test_new_human_on_one_head_cancels_other_heads_stale_visual_answer():
    entered = asyncio.Event()

    class SlowVision:
        async def answer(self, question, frames):
            entered.set()
            await asyncio.Event().wait()
            return "stale cross-head visual answer"

    service = MultimodalOrchestrator(
        config(), {"robot-01": Head(), "robot-02": Head()},
        SlowVision(), asyncio.Lock(),
    )
    task = asyncio.create_task(service.look("robot-02", "What is next to me?"))
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        service.voice_started("robot-01")
        with pytest.raises(RuntimeError, match="newer speech"):
            await asyncio.wait_for(task, timeout=1)
        assert service.hub.user_active("robot-01", time.monotonic())
        assert not service._look_tasks
        service.voice_ended("robot-01")
    finally:
        await service.close()


async def test_cross_head_visual_tools_wait_for_current_human_floor():
    heads = {"robot-01": Head(), "robot-02": Head()}
    model = Vision()
    service = MultimodalOrchestrator(config(), heads, model, asyncio.Lock())
    try:
        service.voice_started("robot-01")
        with pytest.raises(RuntimeError, match="Another human turn"):
            await service.look("robot-02", "What is on the table?")
        assert heads["robot-02"].captures == 0
        assert model.calls == []
        service.voice_ended("robot-01")
        answer = await service.look("robot-02", "What is on the table?")
        assert answer["robot_id"] == "robot-02"
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


async def test_camera_failure_does_not_release_authenticated_human_speech():
    class UnpluggedCamera(Head):
        async def snapshot(self):
            raise RuntimeError("XIAO camera unavailable")

    service = MultimodalOrchestrator(
        config(), {"robot-01": UnpluggedCamera(), "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    try:
        service.voice_started("robot-01")
        await asyncio.wait_for(service._capture_tasks["robot-01"], timeout=1)
        assert service.hub.user_active("robot-01", time.monotonic())
        assert not service.hub.frames["robot-01"]
        # The original authenticated voice event was not erased by a JPEG fault.
        assert any(event["kind"] == "human_voice" for event in
                   service.hub.recent_events("robot-01", time.monotonic()))
        service.voice_ended("robot-01")
        assert not service.hub.user_active("robot-01", time.monotonic())
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


async def test_never_speak_delayed_live_scene_after_vlm_timeout():
    class HangingModel:
        async def answer(self, question, frames):
            await asyncio.Event().wait()
            return "An old scene falsely described as current."

    service = MultimodalOrchestrator(
        config(), {"robot-01": Head(), "robot-02": Head()},
        HangingModel(), asyncio.Lock(),
    )
    service._vision_timeout_s = 0.02
    try:
        with pytest.raises(RuntimeError, match="timed out"):
            await service.look("robot-01", "What do you see right now?")
        stats = service.status("robot-01")["software_timings"]
        assert stats["visual_questions"] == 1
        assert stats["visual_answers"] == 0
        assert stats["visual_errors"] == 1
        assert not service._look_tasks
        assert service.hub.frames["robot-01"]  # no fake model answer added
    finally:
        await service.close()


async def test_cancelled_preprocess_retains_native_worker_slot_until_it_exits(monkeypatch):
    """The Pillow thread must own admission until its actual completion."""
    import threading
    import desk_robot.multimodal as media

    started = threading.Event()
    release = threading.Event()
    original = media._prepare

    def stalled_decode(jpeg):
        started.set()
        if not release.wait(2):
            raise RuntimeError("stalled native decoder fixture timed out")
        return original(jpeg)

    monkeypatch.setattr(media, "_prepare", stalled_decode)
    visual = MultimodalOrchestrator(config(), {}, Vision(), asyncio.Lock())
    visual._preprocess_slots = threading.BoundedSemaphore(1)
    pending = asyncio.create_task(visual._prepare_bounded(image()))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        with pytest.raises(RuntimeError, match="JPEG preprocessing busy"):
            await visual._prepare_bounded(image())
        release.set()
        for _ in range(100):
            if visual._preprocess_slots.acquire(blocking=False):
                visual._preprocess_slots.release()
                break
            await asyncio.sleep(.01)
        else:
            pytest.fail("native decoder exit did not release preprocess budget")
        result = await visual._prepare_bounded(image())
        assert result[0].startswith(b"\xff\xd8")
    finally:
        release.set()
        if not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await visual.close()


async def test_preprocess_submission_failure_releases_native_budget(monkeypatch):
    """A stopped executor cannot consume all future image capacity."""
    import threading
    visual = MultimodalOrchestrator(config(), {}, Vision(), asyncio.Lock())
    visual._preprocess_slots = threading.BoundedSemaphore(1)
    visual._preprocess_pool.shutdown(wait=False, cancel_futures=True)
    try:
        with pytest.raises(RuntimeError):
            await visual._prepare_bounded(image())
        assert visual._preprocess_slots.acquire(blocking=False)
        visual._preprocess_slots.release()
    finally:
        await visual.close()


async def test_optional_jpeg_worker_cannot_starve_live_human_visual_preprocess(monkeypatch):
    """A blocked low priority decode cannot occupy both native worker slots."""
    import threading
    import desk_robot.multimodal as media

    started = threading.Event()
    release = threading.Event()

    def decode(jpeg):
        if jpeg == b"background":
            started.set()
            if not release.wait(2):
                raise RuntimeError("background fixture stalled")
        return jpeg, b"fingerprint", 100.0

    monkeypatch.setattr(media, "_prepare", decode)
    visual = MultimodalOrchestrator(config(), {}, Vision(), asyncio.Lock())
    pending = asyncio.create_task(visual._prepare_bounded(b"background"))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        with pytest.raises(RuntimeError, match="Background JPEG preprocessing busy"):
            await visual._prepare_bounded(b"another background")
        # The genuine speech/request owner keeps a native slot even when an
        # optional five-pet camera worker is stuck in decoder I/O.
        assert (await visual._prepare_bounded(
            b"voice", priority=True
        ))[0] == b"voice"
        release.set()
        assert (await pending)[0] == b"background"
    finally:
        release.set()
        if not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await visual.close()


async def test_native_duplex_reuses_current_speech_jpeg_instead_of_second_xiao_capture():
    """Native PCM and the Mac VAD JPEG sampler share one physical camera."""
    head = Head()
    visual = MultimodalOrchestrator(
        config(), {"robot-01": head, "robot-02": Head()}, Vision(),
        asyncio.Lock(),
    )
    try:
        visual._voice_turn_at["robot-01"] = time.monotonic() - 0.1
        first = await visual.capture("robot-01", source="speech")
        assert head.captures == 1
        assert await visual.native_frame("robot-01") is first
        assert head.captures == 1
        # A prior-turn speech JPEG must never be reclassified as live video.
        visual._voice_turn_at["robot-01"] = time.monotonic()
        second = await visual.native_frame("robot-01")
        assert second is not first
        assert head.captures == 2
        assert second.received_at > first.received_at
    finally:
        await visual.close()


async def test_native_duplex_does_not_borrow_background_idle_camera_frame():
    head = Head()
    visual = MultimodalOrchestrator(
        config(), {"robot-01": head, "robot-02": Head()}, Vision(),
        asyncio.Lock(),
    )
    try:
        idle = await visual.capture("robot-01", source="proactive")
        assert head.captures == 1
        frame = await visual.native_frame("robot-01")
        assert head.captures == 2
        assert frame is not idle
        assert frame.source == "speech"
    finally:
        await visual.close()


async def test_native_camera_racing_with_voice_sampler_has_one_real_xiao_capture():
    """Recheck frame freshness after both tasks contend for one camera lock."""
    started, release = asyncio.Event(), asyncio.Event()

    class SlowHead(Head):
        async def snapshot(self):
            started.set()
            await release.wait()
            return await super().snapshot()

    head = SlowHead()
    visual = MultimodalOrchestrator(
        config(), {"robot-01": head, "robot-02": Head()}, Vision(),
        asyncio.Lock(),
    )
    try:
        visual._voice_turn_at["robot-01"] = time.monotonic()
        sampler = asyncio.create_task(
            visual.capture("robot-01", source="speech",
                           reuse_if_recent_s=0.65)
        )
        await asyncio.wait_for(started.wait(), timeout=1)
        native = asyncio.create_task(visual.native_frame("robot-01"))
        await asyncio.sleep(0.005)
        release.set()
        first, second = await asyncio.wait_for(
            asyncio.gather(sampler, native), timeout=3
        )
        assert first is second
        assert head.captures == 1
        assert visual.status("robot-01")["software_timings"][
            "native_speech_camera_reuses"
        ] == 1
    finally:
        release.set()
        await visual.close()


async def test_lost_xiaozhi_voice_transport_cancels_old_visual_turns_without_unmuting():
    visual = MultimodalOrchestrator(
        config(enabled=False),
        {"robot-01": Head(), "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    now = time.monotonic()
    visual.hub.notify("robot-01", "human_voice", now)
    visual.hub.offer("robot-01", image(), now, source="speech")
    visual.hub.remember_heard("robot-01", "asr_before_reset", "A red key", now)
    pending = asyncio.Event()
    task = asyncio.create_task(pending.wait())
    visual._look_tasks["robot-01"] = task
    try:
        visual.voice_transport_unavailable()
        await asyncio.gather(task, return_exceptions=True)
        assert task.cancelled()
        assert not visual.hub.frames["robot-01"]
        assert not visual.hub.heard_history["robot-01"]
        assert visual.hub.user_active("robot-01", time.monotonic())
        assert visual._reconnect_needs_sampler == {"robot-01", "robot-02"}
    finally:
        await visual.close()


async def test_readonly_vision_tool_interpretation_is_ephemeral_per_pet_and_fenced():
    """No raw photo persisted and new voice transport drops previous tool text."""
    heads = {"robot-01": Head(), "robot-02": Head()}
    visual = MultimodalOrchestrator(config(enabled=True), heads, Vision(),
                                    asyncio.Lock())
    try:
        response = await visual.look("robot-01", "What is on my desk?")
        assert response["motor_authorized"] is False
        cues = visual.hub.recent_tool_context("robot-01", time.monotonic())
        assert len(cues) == 1
        assert cues[0]["kind"] == "visual_look"
        assert cues[0]["source"] == "local_vlm_interpretation_not_physical_measurement"
        assert cues[0]["untrusted_text_not_instructions"] is True
        assert cues[0]["motor_authorized"] is False
        assert "dark square" in cues[0]["summary"]
        assert visual.hub.recent_tool_context("robot-02", time.monotonic()) == []
        # The successful local model description is not a durable eyewitness
        # memory. It may be referenced briefly but expires without persistence.
        now = time.monotonic()
        assert visual.hub.recent_tool_context("robot-01", now + 9) == []
        visual.voice_transport_unavailable()
        assert visual.hub.recent_tool_context("robot-01", now + 0.1) == []
        assert not visual.hub.frames["robot-01"]
    finally:
        await visual.close()


def test_readonly_tool_context_rejects_untrusted_shapes():
    hub = CameraFrameHub(["robot-01", "robot-02"])
    for kind, summary, when in (
        ("drive", "forward", 5.0),
        ("visual_look", "", 5.0),
        ("visual_look", "large" * 501, 5.0),
        ("visual_look", "summary", float("nan")),
    ):
        with pytest.raises(ValueError):
            hub.remember_tool("robot-01", kind, summary, when)
    with pytest.raises(ValueError):
        hub.remember_tool("robot-99", "visual_look", "some object", 5.0)


def test_repeated_status_tools_preserve_distinct_job_and_visual_context():
    hub = CameraFrameHub(["robot-01"])
    hub.remember_tool("robot-01", "visual_look", "Maybe a key", 100.0)
    hub.remember_tool("robot-01", "pickup_status", "job queued", 100.1)
    for i in range(10):
        hub.remember_tool(
            "robot-01", "robot_status", f"armed=False seq={i}", 100.2 + i * .1
        )
    context = hub.recent_tool_context("robot-01", 102.0)
    assert len(context) == 3
    assert {entry["kind"] for entry in context} == {
        "visual_look", "pickup_status", "robot_status"
    }
    assert any("seq=9" in entry["summary"] for entry in context)
    assert not any("seq=0" in entry["summary"] for entry in context)


def test_interaction_timeline_orders_camera_sensor_and_tool_without_raw_media():
    """One chronological context view, unlike three unsorted agent memories."""
    hub = CameraFrameHub(["robot-01", "robot-02"])
    hub.offer("robot-01", image(), 100.0, source="proactive")
    hub.notify("robot-01", "touch_tap", 100.3)
    hub.remember_tool("robot-01", "visual_look", "Maybe a red book", 100.6)
    timeline = hub.interaction_timeline("robot-01", 101)
    assert [entry["channel"] for entry in timeline] == [
        "camera", "sensor", "tool",
    ]
    assert timeline[0]["content"] is None
    assert timeline[0]["exposure_timestamp_verified"] is False
    assert timeline[1]["kind"] == "touch_tap"
    assert timeline[2]["content"] == "Maybe a red book"
    assert timeline[2]["untrusted_text_not_instructions"] is True
    assert all(item["physical_action_verified"] is False for item in timeline)
    assert hub.interaction_timeline("robot-02", 101) == []
    assert hub.interaction_timeline("robot-01", 109) == []
    assert len(hub.interaction_timeline("robot-01", 101, limit=2)) == 2
    with pytest.raises(ValueError):
        hub.interaction_timeline("robot-01", float("nan"))
    with pytest.raises(ValueError):
        hub.interaction_timeline("robot-01", 101, limit=99)


async def test_new_human_voice_resets_prior_interpretation_across_fleet():
    visual = MultimodalOrchestrator(
        config(), {"robot-01": Head(), "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    try:
        now = time.monotonic()
        visual.hub.remember_tool("robot-01", "visual_look", "old scene guess", now)
        visual.hub.remember_tool("robot-02", "visual_look", "other old guess", now)
        visual.voice_started("robot-02")
        assert visual.hub.recent_tool_context("robot-01", time.monotonic()) == []
        assert visual.hub.recent_tool_context("robot-02", time.monotonic()) == []
        assert visual.hub.user_active("robot-02", time.monotonic())
        visual.voice_ended("robot-02")
    finally:
        await visual.close()


def test_qwen_style_quiet_window_silences_only_optional_fleet_remarks():
    """Human owns conversation for 800ms after real speech_end, not motors."""
    hub = CameraFrameHub(["robot-01", "robot-02"])
    hub.notify("robot-02", "human_voice", 100.0)
    assert hub.spontaneous_floor_busy(100.5)
    hub.speech_ended("robot-02", 101.0)
    assert hub.spontaneous_floor_busy(101.79)
    assert not hub.spontaneous_floor_busy(101.81)
    # Camera sampling remains independently available in that short pause.
    assert hub.due("robot-01", 101.2)
    hub.notify("robot-01", "human_voice", 102.0)
    assert hub.spontaneous_floor_busy(103.0)
    hub.clear("robot-01")
    assert not hub.spontaneous_floor_busy(103.0)
    with pytest.raises(ValueError):
        hub.spontaneous_floor_busy(float("nan"))


async def test_recent_pet_words_survive_next_vad_but_not_acoustic_hardware_claim():
    """Human reply can refer to the pet's offer, even without memory consent."""
    visual = MultimodalOrchestrator(
        config(), {"robot-01": Head(), "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    try:
        now = time.monotonic()
        visual.hub.remember_spoken(
            "robot-01", "Want to play a little guessing game?", now
        )
        visual.hub.remember_tool(
            "robot-01", "visual_look", "Old uncertain camera guess", now
        )
        visual.voice_started("robot-01")
        timeline = visual.hub.interaction_timeline("robot-01", time.monotonic())
        words = [entry for entry in timeline
                 if entry["channel"] == "robot_speech"]
        assert len(words) == 1
        assert "guessing game" in words[0]["content"]
        assert words[0]["playback_verified"] is False
        assert words[0]["source"] == (
            "mac_tts_transmitted_not_speaker_playback_ack"
        )
        assert not [entry for entry in timeline
                    if entry["channel"] == "tool"]
        assert not [entry for entry in visual.hub.interaction_timeline(
            "robot-02", time.monotonic()
        ) if entry["channel"] == "robot_speech"]
        visual.voice_ended("robot-01")
        assert not [entry for entry in visual.hub.interaction_timeline(
            "robot-01", now + 31
        ) if entry["channel"] == "robot_speech"]
        visual.voice_transport_unavailable()
        assert not visual.hub.spoken_history["robot-01"]
    finally:
        await visual.close()


def test_spoken_receipt_requires_actual_bounded_transmitted_text():
    hub = CameraFrameHub(["robot-01"])
    for value, when in (
        ("", 2.0), ("x" * 281, 2.0), ("said", float("nan")),
    ):
        with pytest.raises(ValueError):
            hub.remember_spoken("robot-01", value, when)
    with pytest.raises(ValueError):
        hub.remember_spoken("robot-02", "not my pet", 2.0)


@pytest.mark.parametrize("source", ["proactive", "sensor", "external_pet"])
async def test_completed_brief_vad_cannot_publish_old_optional_jpeg(
    monkeypatch, source,
):
    """VAD may BEGIN and END during CPU decode; current voice=False is not enough."""
    import threading
    import desk_robot.multimodal as media

    entered = threading.Event()
    release = threading.Event()
    original = media._prepare

    def held_prepare(jpeg):
        entered.set()
        release.wait(timeout=2)
        return original(jpeg)

    monkeypatch.setattr(media, "_prepare", held_prepare)
    service = MultimodalOrchestrator(
        config(enabled=False),
        {"robot-01": Head(), "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    started = time.monotonic()
    task = asyncio.create_task(
        service.offer_proactive("robot-02", image(), started)
        if source == "external_pet" else
        service.capture("robot-02", source=source)
    )
    try:
        assert await asyncio.wait_for(
            asyncio.to_thread(entered.wait, 0.8), timeout=1
        )
        # Human voice on a DIFFERENT head gets the global attention floor.
        service.voice_started("robot-01")
        service.voice_ended("robot-01")
        assert not service.hub.user_active("robot-01", time.monotonic())
        release.set()
        if source == "external_pet":
            assert await asyncio.wait_for(task, timeout=1) is None
        else:
            with pytest.raises(RuntimeError, match="superseded"):
                await asyncio.wait_for(task, timeout=1)
        assert not service.hub.frames["robot-02"]
    finally:
        release.set()
        await service.close()


@pytest.mark.parametrize("source", ["speech", "voice_question"])
@pytest.mark.parametrize("invalidate", ["new_turn", "transport_loss"])
async def test_old_native_camera_cannot_repopulate_new_voice_turn(
    monkeypatch, source, invalidate,
):
    """An /omni-frame HTTP task is not owned by the cancellable VAD sampler."""
    import threading
    import desk_robot.multimodal as media

    entered, release = threading.Event(), threading.Event()
    original = media._prepare

    def held_prepare(jpeg):
        entered.set()
        release.wait(timeout=2)
        return original(jpeg)

    monkeypatch.setattr(media, "_prepare", held_prepare)
    service = MultimodalOrchestrator(
        config(enabled=False),
        {"robot-01": Head(), "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    task = asyncio.create_task(service.capture("robot-01", source=source))
    try:
        assert await asyncio.wait_for(
            asyncio.to_thread(entered.wait, 0.8), timeout=1
        )
        if invalidate == "new_turn":
            service.voice_started("robot-02")
            service.voice_ended("robot-02")
        else:
            service.voice_transport_unavailable()
        release.set()
        with pytest.raises(RuntimeError, match="superseded"):
            await asyncio.wait_for(task, timeout=1)
        assert not service.hub.frames["robot-01"]
        assert service.status("robot-01")["software_timings"]["camera_errors"] >= 1
    finally:
        release.set()
        await service.close()


async def test_external_pet_photo_received_before_brief_voice_is_never_replayed():
    service = MultimodalOrchestrator(
        config(enabled=False),
        {"robot-01": Head(), "robot-02": Head()},
        Vision(), asyncio.Lock(),
    )
    try:
        old_receipt = time.monotonic()
        service.voice_started("robot-01")
        service.voice_ended("robot-01")
        await service.offer_proactive("robot-02", image(), old_receipt)
        assert not service.hub.frames["robot-02"]
        fresh = time.monotonic()
        await service.offer_proactive("robot-02", image(), fresh)
        assert len(service.hub.frames["robot-02"]) == 1
        assert service.hub.frames["robot-02"][-1].received_at == fresh
    finally:
        await service.close()


def test_equal_timestamp_tool_receipt_cannot_overwrite_first_result():
    """Same-clock duplicate completion must not replace authenticated evidence."""
    hub = CameraFrameHub(["robot-01"])
    hub.remember_tool("robot-01", "visual_look", "first completed frame", 10.0)
    hub.remember_tool("robot-01", "visual_look", "late duplicate", 10.0)
    receipts = hub.recent_tool_context("robot-01", 11.0)
    assert len(receipts) == 1
    assert receipts[0]["summary"] == "first completed frame"
    hub.remember_tool("robot-01", "visual_look", "new frame", 10.1)
    assert hub.recent_tool_context("robot-01", 11.0)[0]["summary"] == "new frame"
