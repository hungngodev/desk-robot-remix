"""Proactive pet runtime tests: simulation and host only, never physical evidence."""

import asyncio
import json
import time
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from desk_robot.api import create_app
from desk_robot.config import load_settings
from desk_robot.conversation import Conversation
from desk_robot.memory import MemoryStore
from desk_robot.multimodal import CameraFrameHub
from desk_robot.pet import PetController, _initiative_evidence
from desk_robot.simulator import SimulatedSpeaker
from desk_robot.vision import OllamaScene, SceneChange, VisualChangeGate
from fastapi.testclient import TestClient
from PIL import Image


def jpeg(color: str) -> bytes:
    out = BytesIO()
    Image.new("RGB", (128, 96), color).save(out, "JPEG")
    return out.getvalue()


@pytest.fixture
def fleet():
    return load_settings(Path(__file__).resolve().parents[1] / "config/fleet.simulation.toml")


WHITE = jpeg("white")
RED = jpeg("red")


class ChangingCamera:
    def __init__(self):
        self.frames = [WHITE, WHITE, RED, RED, RED, RED]
        self.calls = 0

    async def snapshot(self):
        index = min(self.calls, len(self.frames) - 1)
        self.calls += 1
        return self.frames[index]


class GroundedChat:
    def __init__(self):
        self.prompts = []

    async def reply(self, history):
        self.prompts.append(history)
        return "A new object! That looks interesting."


class KeyScene:
    def __init__(self):
        self.calls = 0

    async def compare(self, before, after):
        self.calls += 1
        assert before == WHITE and after == RED
        return SceneChange("key", "A flat key appeared on the desk", 0.96)


async def wait_for(predicate, timeout=2):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


def test_visual_change_gate_requires_persistent_difference():
    gate = VisualChangeGate(min_changed_fraction=0.008, confirmations=2)
    assert gate.observe(WHITE) is None
    assert gate.observe(WHITE) is None
    assert gate.observe(RED) is None
    assert gate.observe(RED) == WHITE
    assert gate.observe(RED) is None
    with pytest.raises(ValueError):
        VisualChangeGate(min_changed_fraction=2)


def test_proactive_frame_gate_reuses_motion_filter_to_ignore_global_exposure():
    from PIL import ImageDraw
    gate = VisualChangeGate(min_changed_fraction=0.008, confirmations=2)
    initial = jpeg("gray")
    exposed = jpeg((175, 175, 175))
    photo = Image.new("RGB", (128, 96), (175, 175, 175))
    ImageDraw.Draw(photo).rectangle((40, 30, 78, 68), fill=(0, 0, 0))
    out = BytesIO()
    photo.save(out, "JPEG", quality=92)
    changed = out.getvalue()
    assert gate.observe(initial) is None
    assert gate.observe(exposed) is None
    assert gate.observe(exposed) is None
    assert gate.observe(changed) is None
    assert gate.observe(changed) == initial
    assert gate.observe(changed) is None


async def test_local_ollama_scene_is_two_frame_and_refuses_uncertain_claims():
    requests = []
    replies = iter([
        {"notable": True, "kind": "key", "description": "A metal key appeared", "confidence": .96},
        {"notable": True, "kind": "key", "description": "A key is here", "confidence": .2},
        {"notable": False, "kind": "none", "description": "", "confidence": 0},
    ])

    def handler(req):
        assert str(req.url) == "http://127.0.0.1:11434/api/chat"
        body = json.loads(req.content)
        assert len(body["messages"][0]["images"]) == 2
        assert body["stream"] is False and body["format"] == "json"
        requests.append(body)
        return httpx.Response(200, json={"message": {"content": json.dumps(next(replies))}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        scene = OllamaScene(client, url="http://127.0.0.1:11434", model="local-vision")
        assert (await scene.compare(WHITE, RED)).kind == "key"
        assert await scene.compare(WHITE, RED) is None
        assert await scene.compare(WHITE, RED) is None
    assert len(requests) == 3


async def test_background_camera_cancel_for_user_speech_does_not_kill_pet_loop(
    fleet, tmp_path
):
    from desk_robot.multimodal import MultimodalOrchestrator

    class SlowFirstDevice:
        def __init__(self):
            self.calls = 0
            self.started = asyncio.Event()
            self.cancelled = False

        async def snapshot(self):
            self.calls += 1
            if self.calls == 1:
                self.started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.cancelled = True
                    raise
            return jpeg("gray")

    device = SlowFirstDevice()
    memory = MemoryStore(tmp_path, [robot.id for robot in fleet.robots])
    conversation = Conversation(
        fleet, GroundedChat(), SimulatedSpeaker(), memory=memory
    )
    pet = PetController(
        fleet, {"robot-01": device}, conversation, memory,
        KeyScene(), interval=.025
    )
    visual = MultimodalOrchestrator(
        fleet, {"robot-01": device}, KeyScene(), asyncio.Lock()
    )
    pet.multimodal = visual
    state = pet.states["robot-01"]
    state.enabled, state.generation, state.quiet = True, 12, True
    worker = asyncio.create_task(pet._observe("robot-01", 12))
    try:
        await asyncio.wait_for(device.started.wait(), timeout=1)
        visual.voice_started("robot-01")
        await wait_for(lambda: device.cancelled)
        assert not worker.done()
        assert state.enabled
        visual.voice_ended("robot-01")
        await wait_for(lambda: device.calls >= 2, timeout=2)
        await wait_for(lambda: state.last_scene_frame_at is not None, timeout=2)
        assert state.last_error is None
        assert memory.count("robot-02") == 0
    finally:
        state.enabled = False
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        await visual.close()
        await pet.close()


@pytest.mark.parametrize("local_object", [False, True])
async def test_explicit_look_preempts_background_vlm_waiting_for_shared_lock(
    fleet, tmp_path,
):
    """Queued observer lacks an inference task, but must yield to the person."""
    class CountingScene:
        def __init__(self):
            self.calls = 0

        async def compare(self, before, after):
            self.calls += 1
            return SceneChange("key", "Old background camera guess", 0.96)

    scene = CountingScene()
    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    pet = PetController(
        fleet,
        {r.id: ChangingCamera() for r in fleet.robots},
        Conversation(fleet, GroundedChat(), SimulatedSpeaker(), memory=memory),
        memory, scene, interval=.01, speech_cooldown=0,
    )
    await pet._vision_lock.acquire()
    try:
        pet.start("robot-01")
        await wait_for(
            lambda: bool(pet._vision_lock._waiters), timeout=2
        )
        # MultimodalOrchestrator.look() calls this before waiting for VLM.
        # The observer already queued here, so cancelling only
        # _vision_inflight would not help: it does not exist yet.
        assert pet._vision_inflight is None
        prior = pet._vision_preemption_epoch
        pet.preempt_background_vision()
        assert pet._vision_preemption_epoch == prior + 1
        pet._vision_lock.release()
        await asyncio.sleep(.1)
        assert scene.calls == 0
        assert pet.status("robot-01")["camera_change_events"] == 0
        assert pet.status("robot-01")["enabled"] is True
        assert memory.count("robot-01") == 0
    finally:
        if pet._vision_lock.locked():
            pet._vision_lock.release()
        await pet.close()


async def test_sensor_capture_burst_is_consumed_by_one_proactive_scene_owner(
    fleet, tmp_path, local_object
):
    """A hardware sensor event must reach the scene gate, not just RAM JPEGs."""
    from PIL import ImageDraw
    from desk_robot.multimodal import MultimodalOrchestrator

    before = jpeg("gray")
    if local_object:
        picture = Image.new("RGB", (128, 96), "gray")
        ImageDraw.Draw(picture).rectangle((36, 27, 76, 67), fill="black")
        output = BytesIO()
        picture.save(output, "JPEG", quality=92)
        after = output.getvalue()
    else:
        after = jpeg((175, 175, 175))  # lighting alone is not a new object

    class Device:
        def __init__(self):
            self.calls = 0

        async def snapshot(self):
            self.calls += 1
            return before if self.calls == 1 else after

    class ObservedScene:
        def __init__(self):
            self.calls = 0

        async def compare(self, earlier, newer):
            self.calls += 1
            assert earlier != newer
            return SceneChange("object", "A new small object appeared", .96)

    device, scene = Device(), ObservedScene()
    memory = MemoryStore(tmp_path, [robot.id for robot in fleet.robots])
    chat = Conversation(fleet, GroundedChat(), SimulatedSpeaker(), memory=memory)
    pet = PetController(
        fleet, {"robot-01": device}, chat, memory, scene, interval=.025
    )
    visual = MultimodalOrchestrator(
        fleet, {"robot-01": device}, scene, asyncio.Lock()
    )
    pet.multimodal = visual
    state = pet.states["robot-01"]
    state.enabled, state.generation, state.quiet = True, 42, True
    work = asyncio.create_task(pet._observe("robot-01", 42))
    try:
        await wait_for(lambda: state.last_scene_frame_at is not None)
        assert device.calls == 1
        visual.sensor_event("robot-01", "petting_zone")
        await wait_for(lambda: device.calls >= 3, timeout=4)
        if local_object:
            await wait_for(lambda: scene.calls == 1, timeout=4)
            assert sum(m.kind == "object" for m in memory.recent("robot-01")) == 1
        else:
            await asyncio.sleep(.1)
            assert scene.calls == 0
            assert memory.count("robot-01") == 0
        assert device.calls == 3
        assert memory.count("robot-02") == 0
        assert state.last_error is None
    finally:
        state.enabled = False
        work.cancel()
        await asyncio.gather(work, return_exceptions=True)
        await visual.close()
        await pet.close()


async def test_continuous_stream_changes_reach_real_pet_scene_memory_without_polls(
    fleet, tmp_path,
):
    """A stream alone, without sensor/voice requests, reaches the pet VLM gate."""
    from desk_robot.multimodal import MultimodalOrchestrator

    fleet.mode = "hardware"
    fleet.voice_vision_tools_enabled = True
    fleet.vision_model = "local-vision"

    class StreamingHead:
        def __init__(self):
            self.snapshot_calls = 0
            self.emitted = 0

        async def snapshot(self):
            self.snapshot_calls += 1
            raise AssertionError("Proactive pet must not poll a live camera stream")

        async def stream_frames(self):
            for frame in (WHITE, WHITE, WHITE, RED, RED, RED, RED, RED):
                self.emitted += 1
                yield frame, time.monotonic()
                await asyncio.sleep(0.29)

    class StreamingScene:
        def __init__(self):
            self.calls = 0

        async def compare(self, before, after):
            self.calls += 1
            return SceneChange("key", "A real key appeared by the mug", 0.96)

    head, scene = StreamingHead(), StreamingScene()
    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    conversation = Conversation(
        fleet, GroundedChat(), SimulatedSpeaker(), memory=memory
    )
    pet = PetController(
        fleet, {"robot-01": head}, conversation, memory, scene,
        interval=0.035,
    )
    visual = MultimodalOrchestrator(
        fleet, {"robot-01": head}, scene, pet._vision_lock,
    )
    pet.multimodal = visual
    state = pet.states["robot-01"]
    state.enabled, state.generation, state.quiet = True, 17, True
    visual.start_streams()
    observer = asyncio.create_task(pet._observe("robot-01", 17))
    try:
        await wait_for(lambda: state.events >= 1, timeout=5)
        assert scene.calls == 1 and state.events == 1
        assert head.snapshot_calls == 0
        assert memory.count("robot-01") == 1
        remembered = memory.recent("robot-01")[0]
        assert remembered.kind == "key" and remembered.witnessed
        assert remembered.source_robot == "robot-01"
        assert memory.count("robot-02") == 0
        assert not state.last_error
    finally:
        state.enabled = False
        observer.cancel()
        await asyncio.gather(observer, return_exceptions=True)
        await visual.close()
        await pet.close()




async def test_one_real_change_initiates_one_grounded_speech_and_memory(fleet, tmp_path):
    camera, chat, speaker, scene = ChangingCamera(), GroundedChat(), SimulatedSpeaker(), KeyScene()
    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    conversation = Conversation(fleet, chat, speaker, memory=memory)
    pet = PetController(
        fleet, {r.id: (camera if r.id == "robot-01" else ChangingCamera())
                for r in fleet.robots},
        conversation, memory, scene, interval=.01, speech_cooldown=120,
    )
    pet.start("robot-01")
    await wait_for(lambda: pet.status("robot-01")["spontaneous_speech_turns"] == 1)
    await asyncio.sleep(.05)
    assert scene.calls == 1
    assert len(speaker.spoken) == 1
    assert chat.prompts and "A flat key appeared" in chat.prompts[0][1]["content"]
    assert memory.count("robot-01") == 2
    assert all(memory.count(r.id) == 0 for r in fleet.robots if r.id != "robot-01")
    records = memory.recent("robot-01")
    assert records[0].kind == "own_utterance"
    assert records[1].kind == "key" and records[1].witnessed
    assert pet.status("robot-01")["motor_control_enabled_by_pet"] is False
    assert pet.status("robot-01")["source_capture_timestamp_verified"] is False
    await pet.close()


async def test_five_cameras_one_group_speech_and_distinct_eyewitness_memories(fleet, tmp_path):
    cameras = {r.id: ChangingCamera() for r in fleet.robots}
    memory = MemoryStore(tmp_path, list(cameras))
    chat, speaker, scene = GroundedChat(), SimulatedSpeaker(), KeyScene()
    conversation = Conversation(fleet, chat, speaker, memory=memory)
    pet = PetController(
        fleet, cameras, conversation, memory, scene,
        interval=.01, speech_cooldown=120, group_window=3,
    )
    for robot in cameras:
        pet.start(robot)
    await wait_for(lambda: sum(pet.status(x)["camera_change_events"] for x in cameras) == 5)
    await wait_for(lambda: len(speaker.spoken) == 1)
    assert len(speaker.spoken) == 1
    await wait_for(lambda: sum(pet.status(x)["suppressed_speech_candidates"] for x in cameras) == 4)
    for robot in cameras:
        seen = [m for m in memory.recent(robot) if m.kind == "key"]
        assert len(seen) == 1 and seen[0].source_robot == robot and seen[0].witnessed
    assert all(x.calls >= 4 for x in cameras.values())
    await pet.close()


async def test_quiet_cancels_pending_spontaneous_model_response_without_stopping_observation(
    fleet, tmp_path
):
    entered = asyncio.Event()

    class SlowChat:
        async def reply(self, history):
            entered.set()
            await asyncio.Event().wait()

    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    speaker = SimulatedSpeaker()
    conversation = Conversation(fleet, SlowChat(), speaker, memory=memory)
    pet = PetController(
        fleet, {r.id: ChangingCamera() for r in fleet.robots},
        conversation, memory, KeyScene(), interval=.01, speech_cooldown=0,
    )
    pet.start("robot-01")
    await asyncio.wait_for(entered.wait(), 2)
    state = await pet.set_quiet("robot-01", True)
    assert state["enabled"] and state["quiet"] and state["spontaneous_speech_turns"] == 0
    assert speaker.spoken == []
    await pet.set_quiet("robot-01", False)
    assert pet.status("robot-01")["enabled"]  # still monitoring, not auto-rearmed motion
    await pet.pause("robot-01")
    assert not pet.status("robot-01")["enabled"]
    await pet.close()


def test_pet_api_requires_operator_enable_but_allows_authenticated_stop(fleet, tokens):
    operator = {"Authorization": f"Bearer {tokens['DESK_ROBOT_API_TOKEN']}"}
    tool = {"Authorization": f"Bearer {tokens['DESK_ROBOT_TOOL_TOKEN']}"}
    with TestClient(create_app(fleet)) as client:
        assert client.post("/v1/pet/robot-01/start", headers=tool).status_code == 403
        started = client.post("/v1/pet/robot-01/start", headers=operator)
        assert started.status_code == 200 and started.json()["enabled"]
        assert client.get("/v1/pet/robot-01", headers=tool).json()["enabled"]
        assert client.post(
            "/v1/pet/robot-01/quiet", headers=tool, json={"quiet": True}
        ).status_code == 403
        assert client.post(
            "/v1/pet/robot-01/quiet", headers=operator, json={"quiet": True}
        ).json()["quiet"]
        assert client.post("/v1/pet/robot-01/interrupt", headers=tool).status_code == 200
        assert client.post("/v1/pet/robot-01/pause", headers=tool).status_code == 200
        assert not client.get("/v1/pet/robot-01", headers=tool).json()["enabled"]
        assert client.post("/v1/pet/missing/start", headers=operator).status_code == 409


async def test_touch_edge_from_real_body_status_creates_memory_and_proactive_reply(fleet, tmp_path):
    class TouchHead:
        def __init__(self):
            self.count = 0
            self.calls = 0

        async def status(self):
            self.calls += 1
            if self.calls >= 2:
                self.count = 1
            return {"touch": {"active": False, "count": self.count}}

        async def snapshot(self):
            return WHITE

    head, chat, speaker, scene = TouchHead(), GroundedChat(), SimulatedSpeaker(), KeyScene()
    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    conversation = Conversation(fleet, chat, speaker, memory=memory)
    pet = PetController(fleet, {"robot-01": head}, conversation, memory, scene,
                        interval=.01, speech_cooldown=120)
    try:
        pet.start("robot-01")
        await wait_for(lambda: len(speaker.spoken) == 1)
        assert scene.calls == 0  # A capacitive touch is not a fabricated camera detection.
        assert head.calls >= 2
        events = [m for m in memory.recent("robot-01") if m.kind == "touch"]
        assert len(events) == 1 and events[0].witnessed
        assert events[0].source_robot == "robot-01"
        assert len(speaker.spoken) == 1
        assert pet.status("robot-01")["motor_control_enabled_by_pet"] is False
    finally:
        await pet.close()


async def test_wroom_gesture_counters_feed_firsthand_memory_without_replaying_reset(fleet, tmp_path):
    class GestureHead:
        def __init__(self):
            self.calls = 0
            self.rows = [
                (0, 0, 0, 0),  # baseline
                (1, 0, 0, 0),  # debounced press, no tap until release/window
                (1, 1, 0, 0),
                (3, 1, 1, 0),  # two more presses, one double-tap
                (4, 1, 1, 1),  # a long hold
                (0, 0, 0, 0),  # board reboot; must not replay
            ]

        async def status(self):
            row = self.rows[min(self.calls, len(self.rows) - 1)]
            self.calls += 1
            return {"touch": dict(zip(
                ("count", "tap_count", "double_count", "hold_count"), row, strict=True
            ))}

        async def snapshot(self):
            return WHITE

    head = GestureHead()
    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    speaker = SimulatedSpeaker()
    conversation = Conversation(fleet, GroundedChat(), speaker, memory=memory)
    pet = PetController(
        fleet, {"robot-01": head}, conversation, memory, KeyScene(),
        interval=.01, speech_cooldown=120,
    )
    try:
        pet.start("robot-01")
        await wait_for(lambda: head.calls >= 7, timeout=5)  # CI thread pool can be busy
        kinds = [m.kind for m in memory.recent("robot-01")]
        assert kinds.count("touch_tap") == 1
        assert kinds.count("touch_double") == 1
        assert kinds.count("touch_hold") == 1
        assert all(m.witnessed and m.source_robot == "robot-01"
                   for m in memory.recent("robot-01") if m.kind.startswith("touch_"))
        # The hold may preempt the earlier tap response before transmission.
        assert len(speaker.spoken) <= 1  # never overlapping or replayed speech
        assert pet.status("robot-01")["quiet"]  # deliberate hold enters quiet
        await asyncio.sleep(.05)
        assert len([m for m in memory.recent("robot-01")
                    if m.kind.startswith("touch_")]) == 3
    finally:
        await pet.close()


async def test_opt_in_camera_observation_shares_only_text_with_correct_fleet_provenance(
    fleet, tmp_path
):
    fleet.fleet_text_sharing_enabled = True
    head, chat, speaker, scene = (
        ChangingCamera(), GroundedChat(), SimulatedSpeaker(), KeyScene()
    )
    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    conversation = Conversation(fleet, chat, speaker, memory=memory)
    pet = PetController(
        fleet, {"robot-01": head}, conversation, memory, scene,
        interval=.01, speech_cooldown=120,
    )
    try:
        pet.start("robot-01")
        await wait_for(lambda: all(
            len([m for m in memory.recent(r.id) if m.kind == "key"]) == 1
            for r in fleet.robots
        ))
        await wait_for(lambda: len(speaker.spoken) == 1)
        observed = []
        for robot in fleet.robots:
            records = [m for m in memory.recent(robot.id) if m.kind == "key"]
            assert len(records) == 1
            item = records[0]
            assert item.summary == "A flat key appeared on the desk"
            assert item.source_robot == "robot-01"
            assert item.witnessed is (robot.id == "robot-01")
            observed.append(item)
        assert len({m.event_id for m in observed}) == 1
        assert len({m.observed_at for m in observed}) == 1
        assert len({m.confidence for m in observed}) == 1
        assert len(speaker.spoken) == 1
        assert scene.calls == 1
        assert pet.status("robot-01")["motor_control_enabled_by_pet"] is False
    finally:
        await pet.close()


async def test_opt_in_touch_event_shares_peer_report_without_reclassifying_as_firsthand(
    fleet, tmp_path
):
    fleet.fleet_text_sharing_enabled = True

    class TouchHead:
        def __init__(self):
            self.calls = 0

        async def status(self):
            self.calls += 1
            count = 1 if self.calls > 1 else 0
            return {"touch": {"count": count, "active": False}}

        async def snapshot(self):
            return WHITE

    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    speaker = SimulatedSpeaker()
    conversation = Conversation(fleet, GroundedChat(), speaker, memory=memory)
    pet = PetController(
        fleet, {"robot-01": TouchHead()}, conversation, memory, KeyScene(),
        interval=.01,
    )
    try:
        pet.start("robot-01")
        await wait_for(lambda: all(
            any(m.kind == "touch" for m in memory.recent(r.id))
            for r in fleet.robots
        ))
        facts = [
            next(m for m in memory.recent(r.id) if m.kind == "touch")
            for r in fleet.robots
        ]
        assert len({m.event_id for m in facts}) == 1
        assert facts[0].witnessed
        assert all(not m.witnessed and m.source_robot == "robot-01"
                   for m in facts[1:])
        assert all(m.summary == "Someone has just touched my body" for m in facts)
    finally:
        await pet.close()


async def test_failing_peer_storage_does_not_erase_eyewitness_or_block_speech(
    fleet, tmp_path
):
    fleet.fleet_text_sharing_enabled = True
    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    remember = memory.remember

    def one_peer_fails(robot_id, *args, **kwargs):
        if robot_id == "robot-03":
            raise OSError("temporary test peer unavailable")
        return remember(robot_id, *args, **kwargs)

    memory.remember = one_peer_fails
    speaker = SimulatedSpeaker()
    conversation = Conversation(fleet, GroundedChat(), speaker, memory=memory)
    pet = PetController(
        fleet, {"robot-01": ChangingCamera()}, conversation,
        memory, KeyScene(), interval=.01,
    )
    try:
        pet.start("robot-01")
        await wait_for(lambda: any(m.kind == "key" for m in memory.recent("robot-05")))
        await wait_for(lambda: len(speaker.spoken) == 1)
        assert memory.count("robot-03") == 0
        fact = next(m for m in memory.recent("robot-01") if m.kind == "key")
        assert fact.witnessed and fact.source_robot == "robot-01"
        fact = next(m for m in memory.recent("robot-05") if m.kind == "key")
        assert not fact.witnessed and fact.source_robot == "robot-01"
        assert "Peer memory robot-03" in pet.status("robot-01")["last_error"]
        assert len(speaker.spoken) == 1
    finally:
        await pet.close()


async def test_old_camera_inference_is_dropped_before_memory_or_spontaneous_speech(
    fleet, tmp_path
):
    class SlowVisualModel:
        def __init__(self):
            self.calls = 0

        async def compare(self, before, after):
            self.calls += 1
            assert before == WHITE and after == RED
            await asyncio.sleep(.06)
            return SceneChange("key", "A key appeared some time ago", 0.96)

    scene = SlowVisualModel()
    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    speaker = SimulatedSpeaker()
    chat = GroundedChat()
    pet = PetController(
        fleet, {"robot-01": ChangingCamera()},
        Conversation(fleet, chat, speaker, memory=memory),
        memory, scene, interval=.01, max_observation_age=.02,
    )
    try:
        pet.start("robot-01")
        await wait_for(lambda: scene.calls >= 1)
        await wait_for(lambda: pet.status("robot-01")["stale_camera_events_dropped"] == 1)
        assert pet.status("robot-01")["camera_change_events"] == 0
        assert memory.count("robot-01") == 0
        assert not speaker.spoken and not chat.prompts
        assert pet.status("robot-01")["motor_control_enabled_by_pet"] is False
        assert pet.status("robot-01")["source_capture_timestamp_verified"] is False
    finally:
        await pet.close()


async def test_expired_vlm_request_is_actually_cancelled_before_more_camera_work(
    fleet, tmp_path
):
    """Mac does not keep a dead speculative VLM request alive for 45 seconds."""
    class HungScene:
        def __init__(self):
            self.started = asyncio.Event()
            self.cancelled = asyncio.Event()

        async def compare(self, before, after):
            self.started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                raise

    scene = HungScene()
    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    conversation = Conversation(
        fleet, GroundedChat(), SimulatedSpeaker(), memory=memory
    )
    pet = PetController(
        fleet, {"robot-01": ChangingCamera()}, conversation,
        memory, scene, interval=.01, max_observation_age=.3,
    )
    try:
        pet.start("robot-01")
        await asyncio.wait_for(scene.started.wait(), timeout=2)
        await asyncio.wait_for(scene.cancelled.wait(), timeout=2)
        await wait_for(lambda:
            pet.status("robot-01")["stale_camera_events_dropped"] >= 1)
        assert memory.count("robot-01") == 0
        assert pet.states["robot-01"].enabled
        assert pet._vision_inflight is None
        assert pet.status("robot-01")["motor_control_enabled_by_pet"] is False
    finally:
        await pet.close()


async def test_different_observations_of_same_kind_are_not_falsely_coalesced(
    fleet, tmp_path
):
    class StillCamera:
        async def snapshot(self):
            return WHITE

    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    speaker = SimulatedSpeaker()
    pet = PetController(
        fleet, {"robot-01": StillCamera()},
        Conversation(fleet, GroundedChat(), speaker, memory=memory),
        memory, KeyScene(), interval=.05, speech_cooldown=0,
        group_window=10,
    )
    try:
        pet.start("robot-01")
        generation = pet.states["robot-01"].generation
        first = SceneChange("key", "A brass key appeared", 0.95)
        second = SceneChange("key", "A silver key appeared", 0.95)
        pet._consider_speech("robot-01", first, generation)
        await wait_for(lambda: pet.status("robot-01")["spontaneous_speech_turns"] == 1)
        await wait_for(lambda: pet._speech_task is None or pet._speech_task.done())
        pet._consider_speech("robot-01", second, generation)
        await wait_for(lambda: pet.status("robot-01")["spontaneous_speech_turns"] == 2)
        await wait_for(lambda: pet._speech_task is None or pet._speech_task.done())
        # Matching semantic text with different case and whitespace is one event.
        pet._consider_speech(
            "robot-01", SceneChange("key", "  A   SILVER key appeared ", 0.95),
            generation,
        )
        await asyncio.sleep(.02)
        assert len(speaker.spoken) == 2
        assert pet.status("robot-01")["suppressed_speech_candidates"] == 1
        assert len(pet._event_kinds) == 2
    finally:
        await pet.close()


async def test_independent_touch_poll_silences_pet_while_camera_vlm_is_blocked(
    fleet, tmp_path
):
    class WaitingScene:
        def __init__(self):
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def compare(self, before, after):
            self.entered.set()
            await self.release.wait()
            return SceneChange("key", "A new key appeared on the desk", .95)

    class LiveTouchAndCamera(ChangingCamera):
        def __init__(self):
            super().__init__()
            self.hold = False
            self.status_calls = 0

        async def status(self):
            self.status_calls += 1
            return {
                "touch": {
                    "active": self.hold,
                    "count": 1 if self.hold else 0,
                    "tap_count": 0,
                    "double_count": 0,
                    "hold_count": 1 if self.hold else 0,
                }
            }

    scene = WaitingScene()
    head = LiveTouchAndCamera()
    speaker = SimulatedSpeaker()
    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    pet = PetController(
        fleet, {"robot-01": head},
        Conversation(fleet, GroundedChat(), speaker, memory=memory),
        memory, scene, interval=.01, touch_interval=.01,
    )
    try:
        pet.start("robot-01")
        await asyncio.wait_for(scene.entered.wait(), 2)
        head.hold = True
        # The VLM is still blocked. This must not wait for inference to finish.
        await wait_for(lambda: pet.status("robot-01")["quiet"])
        assert not scene.release.is_set()
        assert pet.status("robot-01")["motor_control_enabled_by_pet"] is False
        assert not speaker.spoken
        await wait_for(
            lambda: any(m.kind == "touch_hold" for m in memory.recent("robot-01"))
        )
        scene.release.set()
        await wait_for(lambda: pet.status("robot-01")["camera_change_events"] == 2)
        await asyncio.sleep(.02)
        assert not speaker.spoken
        await pet.pause("robot-01")
        after_pause = head.status_calls
        await asyncio.sleep(.05)
        assert head.status_calls == after_pause
    finally:
        scene.release.set()
        await pet.close()


async def test_touch_bridge_disconnect_disables_pet_without_automatic_reconnect(
    fleet, tmp_path
):
    from desk_robot.transport import HeadError

    class LostStatusHead:
        def __init__(self):
            self.status_calls = 0

        async def status(self):
            self.status_calls += 1
            if self.status_calls == 1:
                return {"touch": {"active": False, "count": 0}}
            raise HeadError("body UART lost")

        async def snapshot(self):
            return WHITE

    head = LostStatusHead()
    speaker = SimulatedSpeaker()
    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    pet = PetController(
        fleet, {"robot-01": head},
        Conversation(fleet, GroundedChat(), speaker, memory=memory),
        memory, KeyScene(), interval=.01, touch_interval=.01,
    )
    try:
        pet.start("robot-01")
        await wait_for(lambda: not pet.status("robot-01")["enabled"])
        assert "HeadError" in pet.status("robot-01")["last_error"]
        before = head.status_calls
        await asyncio.sleep(.04)
        assert head.status_calls == before
        assert not speaker.spoken
        assert pet.status("robot-01")["motor_control_enabled_by_pet"] is False
    finally:
        await pet.close()


async def test_local_wroom_fault_transition_cancels_mac_motion_authority(fleet, tmp_path):
    # This is the missing bridge between independent WROOM reflexes and
    # any outstanding Mac jobs or one-use operator permits.
    observed = []
    async def cancel_job(robot_id):
        observed.append(robot_id)

    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    conversation = Conversation(fleet, GroundedChat(), SimulatedSpeaker(), memory=memory)
    pet = PetController(
        fleet, {}, conversation, memory, KeyScene(), on_local_fault=cancel_job
    )
    state = pet.states["robot-01"]
    state.enabled, state.generation = True, 4
    def body(fault, ready=False):
        return {"safety": {"required": True, "ready": ready,
                           "fault": fault, "sensor": 2}}
    try:
        await pet._observe_body_safety("robot-01", 4, body("none", True))
        await pet._observe_body_safety("robot-01", 4, body("floor_out_of_range"))
        await pet._observe_body_safety("robot-01", 4, body("floor_out_of_range"))
        assert observed == ["robot-01"]
        await pet._observe_body_safety("robot-01", 4, body("none", True))
        await pet._observe_body_safety("robot-01", 4, body("front_obstacle"))
        assert observed == ["robot-01", "robot-01"]
        assert state.safety_fault_events == 2
        assert len([m for m in memory.recent("robot-01")
                    if m.kind == "safety_fault"]) == 2
        assert memory.count("robot-02") == 0
    finally:
        state.enabled = False
        await pet.close()


async def test_wroom_stop_callback_runs_before_any_safety_camera_request(
    fleet, tmp_path,
):
    observed = []

    async def stop(robot_id):
        observed.append(("stop", robot_id))

    class CameraHook:
        hub = SimpleNamespace(discard_video=lambda robot_id: None)

        def sensor_event(self, robot_id, kind):
            observed.append(("camera", robot_id, kind))

    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    conversation = Conversation(fleet, GroundedChat(), SimulatedSpeaker(),
                                memory=memory)
    pet = PetController(
        fleet, {}, conversation, memory, KeyScene(), on_local_fault=stop,
    )
    pet.multimodal = CameraHook()
    state = pet.states["robot-01"]
    state.enabled, state.generation = True, 19
    try:
        await pet._observe_body_safety("robot-01", 19, {
            "safety": {"required": True, "ready": True, "fault": "none"},
        })
        await pet._observe_body_safety("robot-01", 19, {
            "safety": {"required": True, "ready": False,
                       "fault": "floor_out_of_range", "sensor": 0},
        })
        assert observed == [
            ("stop", "robot-01"),
            ("camera", "robot-01", "safety_fault"),
        ]
        assert any(record.kind == "safety_fault"
                   for record in memory.recent("robot-01"))
    finally:
        state.enabled = False
        await pet.close()


async def test_local_wroom_safety_transitions_are_firsthand_not_replayed(fleet, tmp_path):
    class GuardedHead:
        def __init__(self):
            self.calls = 0
            self.faults = [
                ("missing_sample", False),  # startup baseline, not a new event
                ("missing_sample", False),
                ("none", True),            # operator locally cleared the latch
                ("floor_out_of_range", False),
                ("floor_out_of_range", False),
                ("none", True),
                ("front_obstacle", False),
                ("front_obstacle", False),
            ]

        async def status(self):
            index = min(self.calls, len(self.faults) - 1)
            self.calls += 1
            fault, ready = self.faults[index]
            return {
                "touch": {"active": False, "count": 0, "tap_count": 0,
                          "double_count": 0, "hold_count": 0},
                "safety": {"required": True, "ready": ready,
                           "fault": fault, "sensor": 2},
            }

        async def snapshot(self):
            return WHITE

    head = GuardedHead()
    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    speaker = SimulatedSpeaker()
    conversation = Conversation(fleet, GroundedChat(), speaker, memory=memory)
    pet = PetController(
        fleet, {"robot-01": head}, conversation, memory, KeyScene(),
        interval=.01, touch_interval=.01,
    )
    try:
        pet.start("robot-01")
        await wait_for(lambda: head.calls >= 10)
        status = pet.status("robot-01")
        assert status["local_safety_fault_events"] == 2
        assert status["last_local_safety_fault"] == "front_obstacle"
        records = [record for record in memory.recent("robot-01")
                   if record.kind == "safety_fault"]
        assert len(records) == 2
        assert all(record.witnessed and record.source_robot == "robot-01"
                   for record in records)
        assert "floor_out_of_range" in records[1].summary
        assert "front_obstacle" in records[0].summary
        assert not speaker.spoken  # no generated safety speech, motion or rearm
        assert status["motor_control_enabled_by_pet"] is False
        await pet.pause("robot-01")
        # Explicit re-enable resets the status baseline, not the stored facts.
        pet.start("robot-01")
        await wait_for(lambda: head.calls >= 12)
        assert pet.status("robot-01")["local_safety_fault_events"] == 2
    finally:
        await pet.close()


async def test_operator_selected_peer_memory_share_recovers_pr4_without_rewriting_witness(
    fleet, tmp_path
):
    fleet.fleet_text_sharing_enabled = True
    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    event_id = "witness_event_123"
    memory.remember(
        "robot-01", event_id, "I saw a key near my left wheel",
        kind="key", source_robot="robot-01", witnessed=True,
        observed_at=100.0, confidence=0.95,
    )
    conversation = Conversation(
        fleet, GroundedChat(), SimulatedSpeaker(), memory=memory
    )
    pet = PetController(fleet, {}, conversation, memory, KeyScene())
    try:
        result = await pet.share_with_peer("robot-01", "robot-02", event_id)
        assert result == {
            "from_robot": "robot-01",
            "to_robot": "robot-02",
            "source_robot": "robot-01",
            "event_id": event_id,
            "stored": True,
            "witnessed": False,
            "text_only": True,
        }
        assert (await pet.share_with_peer("robot-01", "robot-02", event_id))["stored"] is False
        assert memory.count("robot-01") == memory.count("robot-02") == 1
        assert memory.count("robot-03") == 0
        origin, received = memory.recent("robot-01")[0], memory.recent("robot-02")[0]
        assert origin.witnessed and origin.source_robot == "robot-01"
        assert not received.witnessed and received.source_robot == "robot-01"
        assert received.kind == origin.kind and received.summary == origin.summary
        assert received.observed_at == origin.observed_at
        assert received.confidence == origin.confidence

        with pytest.raises(ValueError, match="eyewitness"):
            await pet.share_with_peer("robot-02", "robot-03", event_id)
        with pytest.raises(ValueError, match="different"):
            await pet.share_with_peer("robot-01", "robot-01", event_id)
        with pytest.raises(ValueError, match="Unknown or expired"):
            await pet.share_with_peer("robot-01", "robot-03", "missing")
        fleet.fleet_text_sharing_enabled = False
        with pytest.raises(ValueError, match="explicit local"):
            await pet.share_with_peer("robot-01", "robot-03", event_id)
        assert memory.count("robot-03") == 0
    finally:
        await pet.close()


def test_selected_peer_share_api_requires_operator_and_existing_opt_in(fleet, tokens, tmp_path):
    fleet.memory_dir = tmp_path / "memory"
    fleet.fleet_text_sharing_enabled = True
    tool = {"Authorization": f"Bearer {tokens['DESK_ROBOT_TOOL_TOKEN']}"}
    operator = {"Authorization": f"Bearer {tokens['DESK_ROBOT_API_TOKEN']}"}
    with TestClient(create_app(fleet)) as client:
        memory = client.app.state.runtime.memory
        memory.remember(
            "robot-01", "event123", "A wrapped candy arrived",
            kind="candy", source_robot="robot-01", witnessed=True
        )
        list_path = "/v1/pet/robot-01/memories"
        assert client.get(list_path, headers=tool).status_code == 403
        listed = client.get(list_path, headers=operator, params={"limit": 1})
        assert listed.status_code == 200, listed.text
        assert listed.json()["robot_id"] == "robot-01"
        assert listed.json()["records"][0]["event_id"] == "event123"
        assert listed.json()["records"][0]["witnessed"] is True
        assert client.get(list_path, headers=operator, params={"limit": 51}).status_code == 422
        assert client.get("/v1/pet/missing/memories", headers=operator).status_code == 404
        path = "/v1/pet/robot-01/share"
        payload = {"to_robot": "robot-03", "event_id": "event123"}
        assert client.post(path, headers=tool, json=payload).status_code == 403
        assert memory.count("robot-03") == 0
        result = client.post(path, headers=operator, json=payload)
        assert result.status_code == 200, result.text
        assert result.json()["stored"] is True
        assert client.post(path, headers=operator, json=payload).json()["stored"] is False
        assert memory.recent("robot-03")[0].witnessed is False
        listing = client.get("/v1/pet/robot-03/memories", headers=operator)
        assert listing.json()["records"][0]["witnessed"] is False
        assert listing.json()["records"][0]["source_robot"] == "robot-01"
        assert memory.count("robot-02") == 0
        assert client.post(
            path, headers=operator,
            json={"to_robot": "robot-03", "event_id": "bad name"}
        ).status_code == 422
        assert client.post(
            path, headers=operator,
            json={"to_robot": "missing", "event_id": "event123"}
        ).status_code == 404
        fleet.fleet_text_sharing_enabled = False
        assert client.post(path, headers=operator, json=payload).status_code == 400


async def test_selective_only_mode_copies_single_existing_eyewitness_event(fleet, tmp_path):
    fleet.fleet_text_sharing_enabled = True
    fleet.fleet_text_auto_fanout_enabled = False
    camera, scene = ChangingCamera(), KeyScene()
    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    conversation = Conversation(
        fleet, GroundedChat(), SimulatedSpeaker(), memory=memory
    )
    pet = PetController(
        fleet, {"robot-01": camera}, conversation, memory, scene,
        interval=.01, speech_cooldown=120,
    )
    try:
        pet.start("robot-01")
        await wait_for(lambda: any(
            row.kind == "key" for row in memory.recent("robot-01")
        ))
        observed = next(
            row for row in memory.recent("robot-01") if row.kind == "key"
        )
        assert observed.witnessed
        assert memory.count("robot-02") == memory.count("robot-03") == 0
        shared = await pet.share_with_peer(
            "robot-01", "robot-03", observed.event_id
        )
        assert shared["stored"] and not shared["witnessed"]
        assert memory.count("robot-02") == 0
        received = memory.recent("robot-03")[0]
        assert received.event_id == observed.event_id
        assert received.source_robot == "robot-01" and not received.witnessed
    finally:
        await pet.close()



async def test_hardware_aux_sensors_react_only_to_real_calibrated_edges(fleet, tmp_path):
    from desk_robot.aux import validate_aux

    fleet.mode = "hardware"
    fleet.robots[0].nose_twist_threshold_counts = 500
    fleet.robots[0].squeeze_raw_threshold = 8000
    fleet.robots[0].proximity_near_raw_threshold = 120
    memory = MemoryStore(tmp_path, [robot.id for robot in fleet.robots])
    chat = Conversation(fleet, GroundedChat(), SimulatedSpeaker(), memory=memory)
    pet = PetController(fleet, {}, chat, memory, KeyScene())
    robot_id = "robot-01"
    state = pet.states[robot_id]
    state.enabled = True
    state.generation = 3

    def report(soc, nose, pressure, nearby):
        return {
            "robot_id": robot_id,
            "pulse": {"present": False, "valid": False, "part_id": 0,
                      "red": 0, "ir": 0, "age_ms": 0, "bpm": None, "medical": False},
            "angles": {"raw": [nose, 0, 0], "present_mask": 1,
                       "valid_mask": 1, "magnet": [32, 0, 0]},
            "force": {"adc": [pressure, 0], "jaw_seq": 10, "valid": True, "calibrated": False},
            "climate": {"temp_centi": 2150, "rh_centi": 5000, "valid": True},
            "power": {"cell_mv": 3700, "soc_centi": soc, "bus_mv": 5100,
                      "shunt_uv": 5, "fuel_valid": True, "monitor_valid": True,
                      "current_calibrated": False},
            "proximity": {"raw": nearby, "valid": True, "gesture": 0,
                          "gesture_events": 0, "physically_qualified": False},
        }

    try:
        first = report(5000, 100, 100, 40)
        assert validate_aux(first, robot_id) is first
        await pet._observe_aux(robot_id, 3, first)
        assert not any(m.kind in {"battery_low", "nose_twist", "squeeze", "nearby_object"}
                       for m in memory.recent(robot_id))
        await pet._observe_aux(robot_id, 3, report(1900, 900, 10000, 150))
        kind = {m.kind for m in memory.recent(robot_id)}
        assert {"battery_low", "nose_twist", "squeeze", "nearby_object"} <= kind
        assert memory.count("robot-02") == 0
        before = sum(m.kind in kind for m in memory.recent(robot_id))
        await pet._observe_aux(robot_id, 3, report(1900, 900, 10000, 150))
        assert sum(m.kind in kind for m in memory.recent(robot_id)) == before

        # Same readings after invalid sensor data must not imply continuing contact.
        invalid = report(1900, 900, 10000, 150)
        invalid["force"]["valid"] = False
        invalid["proximity"]["valid"] = False
        invalid["power"]["fuel_valid"] = False
        invalid["angles"]["valid_mask"] = 0
        await pet._observe_aux(robot_id, 3, invalid)
        assert sum(m.kind in kind for m in memory.recent(robot_id)) == before
        state.enabled = False
        await pet._observe_aux(robot_id, 3, report(1900, 2000, 15000, 200))
        assert sum(m.kind in kind for m in memory.recent(robot_id)) == before
    finally:
        state.enabled = False
        await pet.close()


async def test_optical_paw_requires_fresh_fifo_edges_and_measured_threshold(fleet, tmp_path):
    """Optical paw contact is an interaction, not a medical pulse reading."""
    fleet.mode = "hardware"
    robot = fleet.robots[0]
    robot.paw_contact_ir_raw_threshold = 10000
    robot.paw_contact_interactions_qualified = True
    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    chat = Conversation(fleet, GroundedChat(), SimulatedSpeaker(), memory=memory)
    pet = PetController(fleet, {}, chat, memory, KeyScene())
    state = pet.states["robot-01"]
    state.enabled, state.generation = True, 7

    def report(seq, ir, *, age=20, valid=True):
        return {
            "robot_id": "robot-01",
            "pulse": {
                "present": True, "valid": valid, "part_id": 0x15,
                "red": 1000, "ir": ir, "age_ms": age, "seq": seq,
                "bpm": None, "medical": False,
            },
            "angles": {"raw": [0, 0, 0], "present_mask": 0,
                       "valid_mask": 0, "magnet": [0, 0, 0]},
            "force": {"adc": [0, 0], "jaw_seq": 0, "valid": False,
                      "calibrated": False},
            "climate": {"temp_centi": 0, "rh_centi": 0, "valid": False},
            "power": {"cell_mv": 0, "soc_centi": 0, "bus_mv": 0,
                      "shunt_uv": 0, "fuel_valid": False,
                      "monitor_valid": False, "current_calibrated": False},
            "proximity": {"raw": 0, "valid": False, "gesture": 0,
                          "gesture_events": 0, "physically_qualified": False},
        }

    try:
        async def observe(seq, ir, **kwargs):
            await pet._observe_aux("robot-01", 7, report(seq, ir, **kwargs))

        await observe(1, 1000)  # initial optical baseline never announces touch
        await observe(2, 30000)
        await observe(2, 30000)  # HTTP replay does not count twice
        assert not any(m.kind == "paw_contact" for m in memory.recent("robot-01"))
        await observe(3, 33000)
        assert sum(m.kind == "paw_contact" for m in memory.recent("robot-01")) == 1
        await observe(4, 30000)
        await observe(5, 1000)
        await observe(6, 1000)  # two confirmed low samples release pad
        await observe(7, 30000)
        await observe(8, 33000)
        assert sum(m.kind == "paw_contact" for m in memory.recent("robot-01")) == 2
        await observe(9, 1000, age=400)  # stale sample invalidates baseline
        await observe(1, 30000)  # firmware reboot: rebaseline, no old replay
        await observe(1, 30000)
        assert sum(m.kind == "paw_contact" for m in memory.recent("robot-01")) == 2
        assert memory.count("robot-02") == 0
        assert not any("heartbeat" in m.summary.lower()
                       for m in memory.recent("robot-01"))
    finally:
        state.enabled = False
        await pet.close()


async def test_optical_paw_is_silent_until_hardware_qualified(fleet, tmp_path):
    fleet.mode = "hardware"
    fleet.robots[0].paw_contact_ir_raw_threshold = 10000
    # The unverified flag is deliberately still false.
    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    chat = Conversation(fleet, GroundedChat(), SimulatedSpeaker(), memory=memory)
    pet = PetController(fleet, {}, chat, memory, KeyScene())
    state = pet.states["robot-01"]
    state.enabled, state.generation = True, 11
    from desk_robot.aux import validate_aux
    payload = {
        "robot_id": "robot-01",
        "pulse": {"present": True, "valid": True, "part_id": 21,
                  "red": 200, "ir": 120000, "age_ms": 20, "seq": 3,
                  "bpm": None, "medical": False},
        "angles": {"raw": [0, 0, 0], "present_mask": 0,
                   "valid_mask": 0, "magnet": [0, 0, 0]},
        "force": {"adc": [0, 0], "jaw_seq": 0, "valid": False,
                  "calibrated": False},
        "climate": {"temp_centi": 0, "rh_centi": 0, "valid": False},
        "power": {"cell_mv": 0, "soc_centi": 0, "bus_mv": 0,
                  "shunt_uv": 0, "fuel_valid": False,
                  "monitor_valid": False, "current_calibrated": False},
        "proximity": {"raw": 0, "valid": False, "gesture": 0,
                      "gesture_events": 0, "physically_qualified": False},
    }
    try:
        for seq in (3, 4, 5):
            payload["pulse"]["seq"] = seq
            await pet._observe_aux("robot-01", 11, validate_aux(payload, "robot-01"))
        assert not any(m.kind == "paw_contact" for m in memory.recent("robot-01"))
    finally:
        state.enabled = False
        await pet.close()


async def test_sht41_ambient_change_requires_fresh_distinct_samples(fleet, tmp_path):
    """No guessed room weather, replayed climate frames or unqualified voice."""
    fleet.mode = "hardware"
    robot = fleet.robots[0]
    robot.ambient_interactions_qualified = True
    robot.ambient_temp_change_centi = 200
    robot.ambient_humidity_change_centi = 800
    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    chat = Conversation(fleet, GroundedChat(), SimulatedSpeaker(), memory=memory)
    pet = PetController(fleet, {}, chat, memory, KeyScene())
    state = pet.states["robot-01"]
    state.enabled, state.generation = True, 13

    def report(seq, temp, rh, *, valid=True, age=50):
        return {
            "robot_id": "robot-01",
            "pulse": {"present": False, "valid": False, "part_id": 0,
                      "red": 0, "ir": 0, "age_ms": 0, "bpm": None, "medical": False},
            "angles": {"raw": [0, 0, 0], "present_mask": 0,
                       "valid_mask": 0, "magnet": [0, 0, 0]},
            "force": {"adc": [0, 0], "jaw_seq": 0,
                      "valid": False, "calibrated": False},
            "climate": {"temp_centi": temp, "rh_centi": rh,
                        "valid": valid, "seq": seq, "age_ms": age},
            "power": {"cell_mv": 0, "soc_centi": 0, "bus_mv": 0,
                      "shunt_uv": 0, "fuel_valid": False,
                      "monitor_valid": False, "current_calibrated": False},
            "proximity": {"raw": 0, "valid": False, "gesture": 0,
                          "gesture_events": 0, "physically_qualified": False},
        }

    try:
        async def observe(seq, temp, rh, **kwargs):
            await pet._observe_aux("robot-01", 13, report(seq, temp, rh, **kwargs))

        await observe(20, 2200, 5000)  # environmental baseline only
        await observe(21, 2440, 5000)
        await observe(21, 2440, 5000)  # replay cannot confirm a change
        assert not any(m.kind == "ambient_shift" for m in memory.recent("robot-01"))
        await observe(22, 2450, 5000)
        assert sum(m.kind == "ambient_shift" for m in memory.recent("robot-01")) == 1
        await observe(23, 2450, 5000)
        assert sum(m.kind == "ambient_shift" for m in memory.recent("robot-01")) == 1
        await observe(24, 2450, 6200)
        await observe(25, 2450, 6300)
        assert sum(m.kind == "ambient_shift" for m in memory.recent("robot-01")) == 2
        await observe(26, 2200, 3000, valid=False)
        await observe(1, 2900, 3000)  # reboot baseline does not announce climate
        await observe(1, 2900, 3000)
        assert sum(m.kind == "ambient_shift" for m in memory.recent("robot-01")) == 2
        assert memory.count("robot-02") == 0
    finally:
        state.enabled = False
        await pet.close()


async def test_nfc_toy_tag_events_are_real_per_robot_counter_edges(fleet, tmp_path):
    fleet.mode = "hardware"
    fleet.robots[0].nfc_interactions_qualified = True
    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    chat = Conversation(fleet, GroundedChat(), SimulatedSpeaker(), memory=memory)
    pet = PetController(fleet, {}, chat, memory, KeyScene())
    hub = CameraFrameHub([r.id for r in fleet.robots])
    hub.offer("robot-01", WHITE, time.monotonic(), source="proactive")
    pet.multimodal = SimpleNamespace(hub=hub)
    state = pet.states["robot-01"]
    state.enabled, state.generation = True, 14

    def report(events, token, *, valid=True, seq=40):
        return {
            "robot_id": "robot-01",
            "pulse": {"present": False, "valid": False, "part_id": 0,
                      "red": 0, "ir": 0, "age_ms": 0, "bpm": None, "medical": False},
            "angles": {"raw": [0, 0, 0], "present_mask": 0,
                       "valid_mask": 0, "magnet": [0, 0, 0]},
            "force": {"adc": [0, 0], "jaw_seq": 0,
                      "valid": False, "calibrated": False},
            "climate": {"temp_centi": 0, "rh_centi": 0, "valid": False},
            "power": {"cell_mv": 0, "soc_centi": 0, "bus_mv": 0,
                      "shunt_uv": 0, "fuel_valid": False,
                      "monitor_valid": False, "current_calibrated": False},
            "proximity": {"raw": 0, "valid": False, "gesture": 0,
                          "gesture_events": 0, "physically_qualified": False},
            "nfc": {"v": valid, "t": token if valid else 0,
                    "e": events, "s": seq},
        }

    try:
        await pet._observe_aux("robot-01", 14, report(8, 0))
        await pet._observe_aux("robot-01", 14, report(9, 0x12345678, seq=41))
        assert sum(m.kind == "nfc_tag" for m in memory.recent("robot-01")) == 1
        await pet._observe_aux("robot-01", 14, report(9, 0x12345678, seq=41))
        await pet._observe_aux("robot-01", 14, report(10, 0x12345678, seq=41))
        # The same completed hardware scan cannot authorize a second arrival.
        await pet._observe_aux("robot-01", 14, report(11, 0x12345678, seq=42))
        # Advancing by one hardware scan cannot account for two new tag events.
        assert sum(m.kind == "nfc_tag" for m in memory.recent("robot-01")) == 1
        await pet._observe_aux("robot-01", 14, report(11, 0, valid=False, seq=42))
        await pet._observe_aux("robot-01", 14, report(1, 0xFEDCBA98, seq=1))
        assert sum(m.kind == "nfc_tag" for m in memory.recent("robot-01")) == 1
        await pet._observe_aux("robot-01", 14, report(2, 0xFEDCBA98, seq=2))
        assert sum(m.kind == "nfc_tag" for m in memory.recent("robot-01")) == 2
        assert memory.count("robot-02") == 0
        kinds = [event["kind"] for event in hub.recent_events(
            "robot-01", time.monotonic()
        )]
        assert "nfc_tag" in kinds
        assert hub.due("robot-01", time.monotonic())
        assert not hub.event_history["robot-02"]
    finally:
        state.enabled = False
        await pet.close()


async def test_sensor_interactions_disabled_until_measured_thresholds(fleet, tmp_path):
    fleet.mode = "hardware"
    memory = MemoryStore(tmp_path, [robot.id for robot in fleet.robots])
    chat = Conversation(fleet, GroundedChat(), SimulatedSpeaker(), memory=memory)
    pet = PetController(fleet, {}, chat, memory, KeyScene())
    state = pet.states["robot-01"]
    state.enabled, state.generation = True, 5
    base = {
        "robot_id": "robot-01",
        "pulse": {"present": False, "valid": False, "part_id": 0,
                  "red": 0, "ir": 0, "age_ms": 0, "bpm": None, "medical": False},
        "angles": {"raw": [1000, 0, 0], "present_mask": 1,
                   "valid_mask": 1, "magnet": [32, 0, 0]},
        "force": {"adc": [30000, 30000], "jaw_seq": 10, "valid": True, "calibrated": False},
        "climate": {"temp_centi": 2300, "rh_centi": 5000, "valid": True},
        "power": {"cell_mv": 3700, "soc_centi": 6000, "bus_mv": 5000,
                  "shunt_uv": 0, "fuel_valid": True, "monitor_valid": True,
                  "current_calibrated": False},
        "proximity": {"raw": 255, "valid": True, "gesture": 0,
                      "gesture_events": 0, "physically_qualified": False},
    }
    try:
        await pet._observe_aux("robot-01", 5, base)
        base["angles"]["raw"][0] = 3500
        await pet._observe_aux("robot-01", 5, base)
        assert state.aux_reads == 2
        assert not any(m.kind in {"nose_twist", "squeeze", "nearby_object"}
                       for m in memory.recent("robot-01"))
    finally:
        state.enabled = False
        await pet.close()


async def test_apds9960_gestures_are_real_counter_edges_after_qualification(fleet, tmp_path):
    fleet.mode = "hardware"
    fleet.robots[0].gesture_interactions_qualified = True
    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    chat = Conversation(fleet, GroundedChat(), SimulatedSpeaker(), memory=memory)
    pet = PetController(fleet, {}, chat, memory, KeyScene())
    state = pet.states["robot-01"]
    state.enabled, state.generation = True, 6

    def payload(count, direction, valid=True):
        return {
            "robot_id": "robot-01",
            "pulse": {"present": False, "valid": False, "part_id": 0,
                      "red": 0, "ir": 0, "age_ms": 0, "bpm": None,
                      "medical": False},
            "angles": {"raw": [0, 0, 0], "present_mask": 0,
                       "valid_mask": 0, "magnet": [0, 0, 0]},
            "force": {"adc": [0, 0], "jaw_seq": 0, "valid": False, "calibrated": False},
            "climate": {"temp_centi": 0, "rh_centi": 0, "valid": False},
            "power": {"cell_mv": 0, "soc_centi": 0, "bus_mv": 0,
                      "shunt_uv": 0, "fuel_valid": False, "monitor_valid": False,
                      "current_calibrated": False},
            "proximity": {"raw": 0, "valid": valid, "gesture": direction,
                          "gesture_events": count, "physically_qualified": False},
        }

    try:
        await pet._observe_aux("robot-01", 6, payload(8, 0))
        await pet._observe_aux("robot-01", 6, payload(9, 3))
        assert sum(m.kind == "hand_wave" for m in memory.recent("robot-01")) == 1
        await pet._observe_aux("robot-01", 6, payload(9, 3))
        await pet._observe_aux("robot-01", 6, payload(400, 3))
        assert sum(m.kind == "hand_wave" for m in memory.recent("robot-01")) == 1
        await pet._observe_aux("robot-01", 6, payload(0, 0, False))
        await pet._observe_aux("robot-01", 6, payload(2, 0))
        await pet._observe_aux("robot-01", 6, payload(3, 1))
        assert sum(m.kind == "hand_wave" for m in memory.recent("robot-01")) == 2
    finally:
        state.enabled = False
        await pet.close()

async def test_cap1188_touch_memory_carries_real_edge_provenance(fleet, tmp_path):
    memory = MemoryStore(tmp_path, [robot.id for robot in fleet.robots])
    conversation = Conversation(fleet, GroundedChat(), SimulatedSpeaker(), memory=memory)
    pet = PetController(fleet, {}, conversation, memory, KeyScene(), speech_cooldown=120)
    state = pet.states["robot-01"]
    state.enabled = True
    state.generation = 4
    def extra(cap, good, events):
        return {"mask": 0, "bumper": False, "bumps": 0, "reed": False,
                "reed_count": 0, "pir": False, "pir_count": 0,
                "cap": cap, "cap_ok": good, "cap_events": events}
    try:
        await pet._observe_optional("robot-01", 4, {"extras": extra(0, True, 8)})
        assert not any(m.kind == "petting_zone" for m in memory.recent("robot-01"))
        await pet._observe_optional("robot-01", 4, {"extras": extra(1, True, 9)})
        await pet._observe_optional("robot-01", 4, {"extras": extra(1, True, 9)})
        rows = [m for m in memory.recent("robot-01") if m.kind == "petting_zone"]
        assert len(rows) == 1
        assert rows[0].source_robot == "robot-01" and rows[0].witnessed
        assert "pad 1" in rows[0].summary
        assert memory.count("robot-02") == 0
        await pet._observe_optional("robot-01", 4, {"extras": extra(0, False, 12)})
        await pet._observe_optional("robot-01", 4, {"extras": extra(0, True, 15)})
        await pet._observe_optional("robot-01", 4, {"extras": extra(2, True, 16)})
        assert sum(m.kind == "petting_zone" for m in memory.recent("robot-01")) == 2
        assert any("pad 2" in m.summary for m in memory.recent("robot-01")
                   if m.kind == "petting_zone")
        # Bad fields and a giant counter jump never fabricate remembered touch.
        await pet._observe_optional("robot-01", 4, {"extras": extra(2, True, 600)})
        await pet._observe_optional("robot-01", 4, {"extras": extra(2, "true", 601)})
        assert sum(m.kind == "petting_zone" for m in memory.recent("robot-01")) == 2
        state.enabled = False
        await pet._observe_optional("robot-01", 4, {"extras": extra(2, True, 602)})
        assert sum(m.kind == "petting_zone" for m in memory.recent("robot-01")) == 2
    finally:
        state.enabled = False
        await pet.close()


async def test_optional_bumper_magnet_pir_are_real_masked_fleet_events(fleet, tmp_path):
    cancellations = []
    async def stop(robot_id):
        cancellations.append(robot_id)
    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    conversation = Conversation(fleet, GroundedChat(), SimulatedSpeaker(), memory=memory)
    pet = PetController(fleet, {}, conversation, memory, KeyScene(),
                        on_local_fault=stop, speech_cooldown=120)
    state = pet.states["robot-01"]
    state.enabled = True
    state.generation = 3
    def status(mask, bumps, reed, pir):
        return {"extras": {"mask": mask, "bumper": bool(bumps),
                "bumps": bumps, "reed": bool(reed), "reed_count": reed,
                "pir": bool(pir), "pir_count": pir}}
    try:
        await pet._observe_optional("robot-01", 3, status(7, 0, 0, 0))
        await pet._observe_optional("robot-01", 3, status(7, 1, 1, 1))
        await pet._observe_optional("robot-01", 3, status(7, 1, 1, 1))
        # An independent proactive voice task may legitimately remember its
        # own spoken line while these inputs arrive. Test sensor provenance
        # and deduplication rather than freezing unrelated pet speech.
        sensor_kinds = {"bumper", "magnet", "pir"}
        kinds = [row.kind for row in memory.recent("robot-01")
                 if row.kind in sensor_kinds]
        assert sorted(kinds) == ["bumper", "magnet", "pir"]
        assert cancellations == ["robot-01"]
        assert memory.count("robot-02") == 0
        await pet._observe_optional("robot-01", 3, status(7, 0, 0, 0))
        await pet._observe_optional("robot-01", 3, status(0, 5, 5, 5))
        assert sum(row.kind in sensor_kinds for row in memory.recent("robot-01")) == 3
        assert cancellations == ["robot-01"]
    finally:
        state.enabled = False
        await pet.close()

async def test_real_voice_interrupt_suppresses_proactive_banter_for_cooldown(fleet, tmp_path):
    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    speaker = SimulatedSpeaker()
    conversation = Conversation(fleet, GroundedChat(), speaker, memory=memory)
    pet = PetController(fleet, {}, conversation, memory, KeyScene(),
                        speech_cooldown=120)
    state = pet.states["robot-01"]
    state.enabled, state.generation = True, 1
    try:
        await pet.interrupt("robot-01")
        before = state.suppressed
        pet._consider_speech(
            "robot-01", SceneChange("touch", "Someone touched my head", 1.0), 1
        )
        assert state.suppressed == before + 1
        assert pet._speech_task is None
        assert speaker.spoken == []
    finally:
        state.enabled = False
        await pet.close()


async def test_autonomous_pause_cannot_release_live_human_vad(fleet, tmp_path):
    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    speaker = SimulatedSpeaker()
    conversation = Conversation(fleet, GroundedChat(), speaker, memory=memory)
    pet = PetController(fleet, {}, conversation, memory, KeyScene())
    hub = CameraFrameHub([r.id for r in fleet.robots])
    pet.multimodal = SimpleNamespace(hub=hub)
    hub.notify("robot-02", "human_voice", time.monotonic())
    try:
        await pet.pause("robot-02")
        assert hub.user_active("robot-02", time.monotonic())
        # Only authenticated speech end, not a pet-mode toggle, frees floor.
        hub.speech_ended("robot-02", time.monotonic())
        assert not hub.user_active("robot-02", time.monotonic())
    finally:
        await pet.close()


async def test_unverified_voice_monitor_cannot_launch_spontaneous_speech(
    fleet, tmp_path,
):
    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    speaker = SimulatedSpeaker()
    chat = GroundedChat()
    conversation = Conversation(fleet, chat, speaker, memory=memory)
    pet = PetController(fleet, {}, conversation, memory, KeyScene())
    state = pet.states["robot-01"]
    state.enabled, state.generation = True, 9
    try:
        pet.set_voice_monitor_ready(False)
        assert pet.status("robot-01")["voice_event_monitor_ready"] is False
        pet._consider_speech(
            "robot-01", SceneChange("key", "A real key appeared", 0.98), 9
        )
        assert state.last_initiative_suppression == "voice_monitor_unavailable"
        assert speaker.spoken == []
        assert chat.prompts == []
        assert pet._speech_task is None
        pet.set_voice_monitor_ready(True)
        pet._consider_speech(
            "robot-01", SceneChange("key", "A new brass key appeared", 0.98), 9
        )
        await wait_for(lambda: state.spoken == 1)
        assert len(speaker.spoken) == 1
    finally:
        state.enabled = False
        await pet.close()


async def test_deliberate_touch_can_reply_after_passive_speech_cooldown(fleet, tmp_path):
    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    conversation = Conversation(
        fleet, GroundedChat(), SimulatedSpeaker(), memory=memory
    )
    pet = PetController(
        fleet, {}, conversation, memory, KeyScene(),
        speech_cooldown=120, interaction_cooldown=12,
    )
    state = pet.states["robot-01"]
    state.enabled, state.generation = True, 9
    pet._group_last_spoken = time.monotonic() - 20
    try:
        # A passive humidity change should not make the fleet keep chatting.
        pet._consider_speech(
            "robot-01", SceneChange(
                "ambient_shift", "Local humidity changed", 1.0
            ), 9
        )
        assert pet._speech_task is None
        assert state.last_initiative_suppression == "quiet_voice_or_group_budget"
        # An intentional touch is a different, more responsive interaction.
        pet._consider_speech(
            "robot-01", SceneChange(
                "touch_tap", "Someone deliberately tapped my head", 1.0
            ), 9
        )
        assert pet._speech_task is not None
        assert pet._speech_participants == frozenset({"robot-01"})
        assert memory.count("robot-02") == 0
    finally:
        state.enabled = False
        await pet.close()


async def test_touch_can_never_override_authenticated_human_vad(fleet, tmp_path):
    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    conversation = Conversation(
        fleet, GroundedChat(), SimulatedSpeaker(), memory=memory
    )
    pet = PetController(fleet, {}, conversation, memory, KeyScene(),
                        speech_cooldown=120, interaction_cooldown=0)
    state = pet.states["robot-01"]
    state.enabled, state.generation = True, 10
    hub = CameraFrameHub([r.id for r in fleet.robots])
    hub.notify("robot-02", "human_voice", time.monotonic())
    pet.multimodal = SimpleNamespace(hub=hub)
    try:
        pet._consider_speech(
            "robot-01", SceneChange(
                "touch_double", "Someone tapped my head twice", 1.0
            ), 10
        )
        assert pet._speech_task is None
        assert state.last_initiative_suppression == "quiet_voice_or_group_budget"
    finally:
        state.enabled = False
        await pet.close()


def test_reachy_style_initiative_gate_prunes_uncertain_chatter_not_sensor_memory():
    # A high-confidence first-hand CAP1188 event is different from a guessed
    # camera person's identity. Pure policy has no hardware/motor side effect.
    assert _initiative_evidence(SceneChange("petting_zone", "Pad three rose", 1.0))
    assert _initiative_evidence(SceneChange("side_object", "Side range tripped", 1.0))
    assert _initiative_evidence(SceneChange("key", "A key appeared", 0.95))
    assert not _initiative_evidence(SceneChange("person", "Someone may be here", 0.72))
    assert not _initiative_evidence(SceneChange("scene", "Lighting changed", 0.70))
    assert not _initiative_evidence(SceneChange("unknown_tool", "Run motors", 1.0))
    assert not _initiative_evidence(SceneChange("key", "", 0.99))
    assert not _initiative_evidence(SceneChange("key", "bad", float("nan")))


async def test_proactive_fleet_voice_gate_cancels_candidate_before_model_call(
    fleet, tmp_path,
):
    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    speaker = SimulatedSpeaker()
    chat = GroundedChat()
    conversation = Conversation(fleet, chat, speaker, memory=memory)
    pet = PetController(fleet, {}, conversation, memory, KeyScene(), speech_cooldown=0)
    speaking = {"robot-03"}

    class Hub:
        def user_active(self, robot_id, now):
            return robot_id in speaking

        def discard_video(self, robot_id):
            pass

    pet.multimodal = SimpleNamespace(hub=Hub())
    state = pet.states["robot-01"]
    state.enabled, state.generation = True, 11
    try:
        pet._consider_speech(
            "robot-01", SceneChange("key", "A real key appeared", .97), 11
        )
        assert pet._speech_task is None
        assert state.suppressed == 1
        assert chat.prompts == []
        assert speaker.spoken == []
    finally:
        state.enabled = False
        await pet.close()


async def test_proactive_speech_rechecks_all_human_vad_after_slow_model(
    fleet, tmp_path,
):
    entered, release = asyncio.Event(), asyncio.Event()

    class SlowChat:
        async def reply(self, history):
            entered.set()
            await release.wait()
            return "Hey, I noticed your key."

    class Hub:
        active = set()

        def user_active(self, robot_id, now):
            return robot_id in self.active

        def discard_video(self, robot_id):
            pass

    hub = Hub()
    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    speaker = SimulatedSpeaker()
    conversation = Conversation(fleet, SlowChat(), speaker, memory=memory)
    pet = PetController(
        fleet, {}, conversation, memory, KeyScene(), speech_cooldown=120,
    )
    pet.multimodal = SimpleNamespace(hub=hub)
    state = pet.states["robot-01"]
    state.enabled, state.generation = True, 4
    try:
        pet._consider_speech(
            "robot-01", SceneChange("key", "A physical key appeared", .96), 4
        )
        await asyncio.wait_for(entered.wait(), timeout=2)
        hub.active.add("robot-05")  # unrelated live head owns human turn
        release.set()
        await wait_for(lambda: pet._speech_task is None)
        assert speaker.spoken == []
        assert state.spoken == 0
        assert state.last_initiative_suppression == "human_started_during_reasoning"
        assert pet._group_last_spoken == float("-inf")
    finally:
        release.set()
        state.enabled = False
        await pet.close()


async def test_brief_peer_voice_turn_supersedes_old_pet_reply_after_quiet_window(
    fleet, tmp_path,
):
    """A completed short VAD must fence a slower OLD unsolicited answer."""
    from desk_robot.multimodal import MultimodalOrchestrator

    entered, release = asyncio.Event(), asyncio.Event()

    class SlowChat:
        async def reply(self, history):
            entered.set()
            await release.wait()
            return "I noticed that key."

    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    speaker = SimulatedSpeaker()
    conversation = Conversation(fleet, SlowChat(), speaker, memory=memory)
    pet = PetController(
        fleet, {}, conversation, memory, KeyScene(), speech_cooldown=0,
    )
    # Use the actual fleet voice/camera epoch owner, not a fake VAD flag.
    visual = MultimodalOrchestrator(
        SimpleNamespace(robots=fleet.robots, voice_vision_tools_enabled=False),
        {}, KeyScene(), asyncio.Lock(),
    )
    pet.multimodal = visual
    state = pet.states["robot-01"]
    state.enabled, state.generation = True, 6
    try:
        pet._consider_speech(
            "robot-01", SceneChange("key", "A key appeared", .97), 6
        )
        await asyncio.wait_for(entered.wait(), timeout=2)
        visual.voice_started("robot-05")
        visual.voice_ended("robot-05")
        # Even after the ordinary 800ms quiet pause, the old response must
        # never resurface when the model finally returns.
        await asyncio.sleep(.85)
        assert not visual.hub.spontaneous_floor_busy(time.monotonic())
        release.set()
        await wait_for(lambda: pet._speech_task is None)
        assert speaker.spoken == []
        assert state.spoken == 0
        assert memory.count("robot-01") == 0
        assert state.last_initiative_suppression == "human_started_during_reasoning"
    finally:
        release.set()
        state.enabled = False
        await pet.close()
        await visual.close()


async def test_uncertain_visual_event_is_not_spoken_and_does_not_consume_cooldown(
    fleet, tmp_path,
):
    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    speaker = SimulatedSpeaker()
    conversation = Conversation(fleet, GroundedChat(), speaker, memory=memory)
    pet = PetController(fleet, {}, conversation, memory, KeyScene(), speech_cooldown=120)
    state = pet.states["robot-01"]
    state.enabled, state.generation = True, 7
    try:
        pet._consider_speech("robot-01", SceneChange("scene", "Maybe changed", .60), 7)
        assert state.low_value_speech_candidates == 1
        assert state.suppressed == 1
        assert pet._speech_task is None
        pet._consider_speech("robot-01", SceneChange("key", "A key appeared", .96), 7)
        await wait_for(lambda: state.spoken == 1)
        assert len(speaker.spoken) == 1
    finally:
        state.enabled = False
        await pet.close()


async def test_proactive_source_prompt_does_not_claim_sensor_is_camera(fleet, tmp_path):
    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    chat = GroundedChat()
    speaker = SimulatedSpeaker()
    conversation = Conversation(fleet, chat, speaker, memory=memory)
    pet = PetController(fleet, {}, conversation, memory, KeyScene(), speech_cooldown=0)
    state = pet.states["robot-01"]
    state.enabled, state.generation = True, 24
    try:
        pet._consider_speech(
            "robot-01", SceneChange(
                "paw_contact", "A finger pressed my optical paw sensor", 1.0
            ), 24
        )
        await wait_for(lambda: state.spoken == 1)
        assert "Local physical sensor event" in chat.prompts[0][1]["content"]
        assert "New visual change" not in chat.prompts[0][1]["content"]
        pet._consider_speech(
            "robot-01", SceneChange("key", "A possible key appeared", .96), 24
        )
        await wait_for(lambda: state.spoken == 2)
        assert "Camera model assessment (uncertain)" in chat.prompts[1][1]["content"]
    finally:
        state.enabled = False
        await pet.close()


async def test_spontaneous_model_response_expires_before_old_event_is_spoken(
    fleet, tmp_path,
):
    entered, release = asyncio.Event(), asyncio.Event()

    class DelayedChat:
        async def reply(self, history):
            entered.set()
            await release.wait()
            return "Looks like something interesting happened!"

    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    speaker = SimulatedSpeaker()
    conversation = Conversation(fleet, DelayedChat(), speaker, memory=memory)
    pet = PetController(
        fleet, {}, conversation, memory, KeyScene(),
        max_observation_age=0.02, speech_cooldown=0,
    )
    state = pet.states["robot-01"]
    state.enabled, state.generation = True, 25
    try:
        pet._consider_speech(
            "robot-01", SceneChange("hand_wave", "Real hand wave detected", 1.0),
            25,
        )
        await asyncio.wait_for(entered.wait(), timeout=2)
        await asyncio.sleep(0.04)
        release.set()
        await wait_for(lambda: pet._speech_task is None)
        assert state.spoken == 0
        assert speaker.spoken == []
        assert state.last_initiative_suppression == "event_expired_during_reasoning"
        assert pet._group_last_spoken == float("-inf")
    finally:
        release.set()
        state.enabled = False
        await pet.close()


async def test_proactive_model_rejects_long_uninvited_monologue_without_tts(
    fleet, tmp_path,
):
    class UnboundedChat:
        async def reply(self, history):
            return "A" * 500  # A real slow model ignored the concise prompt.

    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    speaker = SimulatedSpeaker()
    conversation = Conversation(fleet, UnboundedChat(), speaker, memory=memory)
    pet = PetController(fleet, {}, conversation, memory, KeyScene())
    state = pet.states["robot-01"]
    state.enabled, state.generation = True, 12
    try:
        pet._consider_speech(
            "robot-01", SceneChange("key", "A brass key appeared", 0.98), 12
        )
        await wait_for(lambda: pet._speech_task is None)
        assert speaker.spoken == []
        assert state.spoken == 0
        assert state.suppressed == 1
        assert state.last_initiative_suppression == "model_reply_not_concise"
        assert pet._group_last_spoken == float("-inf")
    finally:
        state.enabled = False
        await pet.close()


async def test_opt_in_sensor_event_invites_one_peer_without_extra_audio_owner(
    fleet, tmp_path,
):
    fleet.fleet_text_sharing_enabled = True
    fleet.fleet_social_autonomy_enabled = True
    fleet.fleet_social_min_interval_seconds = 300
    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    speaker = SimulatedSpeaker()
    chat = GroundedChat()
    conversation = Conversation(fleet, chat, speaker, memory=memory)
    pet = PetController(
        fleet, {}, conversation, memory, KeyScene(), speech_cooldown=0,
    )
    for id_ in ("robot-01", "robot-02", "robot-03"):
        pet.states[id_].enabled = True
        pet.states[id_].generation = 2
    try:
        event = SceneChange("nfc_tag", "My toy NFC tag 12345678 arrived", 1.0)
        await pet._store_observation("robot-01", event)
        pet._consider_speech("robot-01", event, 2)
        await wait_for(lambda: pet.states["robot-01"].spoken == 1)
        assert speaker.spoken == [
            ("robot-01", "A new object! That looks interesting."),
            ("robot-02", "A new object! That looks interesting."),
        ]
        assert pet.states["robot-02"].spoken == 1
        assert pet.states["robot-03"].spoken == 0
        assert len(chat.prompts) == 2
        prompt = chat.prompts[1][1]["content"]
        assert "Only Pip observed it" in prompt
        assert "must not pretend it saw or sensed" in prompt
        peer_memories = memory.recent("robot-02")
        assert any(m.kind == "nfc_tag" and not m.witnessed
                   and m.source_robot == "robot-01" for m in peer_memories)
        # Immediate second event cannot manufacture another peer conversation.
        await wait_for(lambda: pet._speech_task is None)
        pet._consider_speech(
            "robot-01", SceneChange(
                "hand_wave", "My local gesture sensor noticed a wave", 1.0
            ), 2,
        )
        await wait_for(lambda: pet.states["robot-01"].spoken == 2)
        assert len(speaker.spoken) == 3
        assert speaker.spoken[-1][0] == "robot-01"
    finally:
        for state in pet.states.values():
            state.enabled = False
        await pet.close()


async def test_social_event_never_shares_without_explicit_local_consent(
    fleet, tmp_path,
):
    fleet.fleet_social_autonomy_enabled = True
    # Deliberately leave fleet_text_sharing_enabled false.
    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    speaker = SimulatedSpeaker()
    conversation = Conversation(fleet, GroundedChat(), speaker, memory=memory)
    pet = PetController(fleet, {}, conversation, memory, KeyScene())
    pet.states["robot-01"].enabled = pet.states["robot-02"].enabled = True
    pet.states["robot-01"].generation = 3
    try:
        pet._consider_speech(
            "robot-01", SceneChange("petting_zone", "Pad 3 was touched", 1.0), 3
        )
        await wait_for(lambda: pet.states["robot-01"].spoken == 1)
        assert len(speaker.spoken) == 1
        assert speaker.spoken[0][0] == "robot-01"
        assert memory.count("robot-02") == 0
    finally:
        for state in pet.states.values():
            state.enabled = False
        await pet.close()


async def test_quiet_on_listening_peer_cancels_shared_social_turn(
    fleet, tmp_path,
):
    fleet.fleet_text_sharing_enabled = True
    fleet.fleet_social_autonomy_enabled = True
    entered = asyncio.Event()
    release = asyncio.Event()

    class SlowChat:
        async def reply(self, history):
            entered.set()
            await release.wait()
            return "Should we try a simple word game?"

    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    speaker = SimulatedSpeaker()
    conversation = Conversation(fleet, SlowChat(), speaker, memory=memory)
    pet = PetController(fleet, {}, conversation, memory, KeyScene())
    for id_ in ("robot-01", "robot-02"):
        pet.states[id_].enabled, pet.states[id_].generation = True, 4
    try:
        pet._consider_speech(
            "robot-01", SceneChange("key", "A brass key appeared", .97), 4
        )
        await asyncio.wait_for(entered.wait(), timeout=2)
        assert pet._speech_participants == frozenset(
            {"robot-01", "robot-02"}
        )
        await asyncio.wait_for(pet.set_quiet("robot-02", True), timeout=3)
        assert conversation.active is None
        assert pet._speech_task is None
        assert pet._speech_participants == frozenset()
        assert speaker.spoken == []
        assert all(state.spoken == 0 for state in pet.states.values())
    finally:
        release.set()
        for state in pet.states.values():
            state.enabled = False
        await pet.close()


async def test_simultaneous_human_interrupts_cancel_one_social_head_flush_once(
    fleet, tmp_path,
):
    fleet.fleet_text_sharing_enabled = True
    fleet.fleet_social_autonomy_enabled = True
    entered = asyncio.Event()

    class SlowChat:
        async def reply(self, history):
            entered.set()
            await asyncio.Event().wait()

    class StopSpeaker(SimulatedSpeaker):
        def __init__(self):
            super().__init__()
            self.stop_requests = []

        async def interrupt(self, robot):
            self.stop_requests.append(robot.id)
            await asyncio.sleep(0.03)  # real device abort RPC is asynchronous

    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    speaker = StopSpeaker()
    conversation = Conversation(fleet, SlowChat(), speaker, memory=memory)
    pet = PetController(fleet, {}, conversation, memory, KeyScene())
    for id_ in ("robot-01", "robot-02"):
        pet.states[id_].enabled, pet.states[id_].generation = True, 8
    try:
        pet._consider_speech(
            "robot-01", SceneChange("key", "A red key appeared", 0.98), 8
        )
        await asyncio.wait_for(entered.wait(), timeout=2)
        await asyncio.wait_for(
            asyncio.gather(
                pet.interrupt("robot-01"), pet.interrupt("robot-02")
            ), timeout=3,
        )
        assert speaker.stop_requests == ["robot-01"]
        assert speaker.spoken == []
        assert conversation.active is None
        assert pet._speech_task is None
        assert pet._speech_participants == frozenset()
    finally:
        for state in pet.states.values():
            state.enabled = False
        await pet.close()



async def test_stale_social_peer_generation_never_enters_audio_session(
    fleet, tmp_path,
):
    fleet.fleet_text_sharing_enabled = True
    fleet.fleet_social_autonomy_enabled = True
    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    speaker = SimulatedSpeaker()
    chat = GroundedChat()
    conversation = Conversation(fleet, chat, speaker, memory=memory)
    pet = PetController(fleet, {}, conversation, memory, KeyScene())
    for rid in ("robot-01", "robot-02"):
        pet.states[rid].enabled, pet.states[rid].generation = True, 9
    try:
        pet._consider_speech(
            "robot-01", SceneChange("key", "A key appeared", .98), 9
        )
        # A pause/restart replaces the invited pet's real connection generation
        # before the asynchronous Mac memory lookup and speech request.
        pet.states["robot-02"].generation = 10
        await wait_for(lambda: pet._speech_task is None)
        assert speaker.spoken == []
        assert chat.prompts == []
        assert pet.states["robot-01"].spoken == 0
        assert pet.states["robot-01"].last_initiative_suppression == (
            "social_peer_or_event_unavailable"
        )
        assert conversation.active is None
    finally:
        for state in pet.states.values():
            state.enabled = False
        await pet.close()


def test_disabled_pet_generation_cannot_schedule_spontaneous_model_work(
    fleet, tmp_path,
):
    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    speaker = SimulatedSpeaker()
    conversation = Conversation(fleet, GroundedChat(), speaker, memory=memory)
    pet = PetController(fleet, {}, conversation, memory, KeyScene())
    pet.states["robot-01"].generation = 2
    pet._consider_speech(
        "robot-01", SceneChange("hand_wave", "A real gesture was detected", 1.0),
        2,
    )
    assert pet._speech_task is None
    assert pet.states["robot-01"].last_initiative_suppression == (
        "pet_disabled_or_generation_changed"
    )


async def test_bmp280_air_pressure_events_require_distinct_measurements_and_opt_in(
    fleet, tmp_path,
):
    """Raw local pressure only, never inferred weather or replayed events."""
    fleet.mode = "hardware"
    robot = fleet.robots[0]
    robot.bmp280_pressure_change_pa = 300
    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    chat = Conversation(fleet, GroundedChat(), SimulatedSpeaker(), memory=memory)
    pet = PetController(fleet, {}, chat, memory, KeyScene())
    state = pet.states["robot-01"]
    state.enabled, state.generation, state.quiet = True, 19, True

    def report(seq, pressure, *, valid=True, age=50):
        return {
            "robot_id": "robot-01",
            "pulse": {"present": False, "valid": False, "part_id": 0,
                      "red": 0, "ir": 0, "age_ms": 0, "bpm": None, "medical": False},
            "angles": {"raw": [0, 0, 0], "present_mask": 0,
                       "valid_mask": 0, "magnet": [0, 0, 0]},
            "force": {"adc": [0, 0], "jaw_seq": 0, "valid": False,
                      "calibrated": False},
            "climate": {"temp_centi": 0, "rh_centi": 0, "valid": False},
            "bmp280": {"present": True, "valid": valid, "chip_id": 0x58,
                       "temp_centi": 2350 if valid else 0,
                       "pressure_pa": pressure if valid else 0,
                       "seq": seq, "age_ms": age, "physically_verified": False},
            "power": {"cell_mv": 0, "soc_centi": 0, "bus_mv": 0,
                      "shunt_uv": 0, "fuel_valid": False,
                      "monitor_valid": False, "current_calibrated": False},
            "proximity": {"raw": 0, "valid": False, "gesture": 0,
                          "gesture_events": 0, "physically_qualified": False},
        }

    try:
        # Even real sensor changes must remain silent without user calibration.
        for seq, pa in ((1, 100000), (2, 100700), (3, 100800)):
            await pet._observe_aux("robot-01", 19, report(seq, pa))
        assert memory.count("robot-01") == 0
        robot.bmp280_interactions_qualified = True
        await pet._observe_aux("robot-01", 19, report(4, 100000))
        await pet._observe_aux("robot-01", 19, report(5, 100500))
        await pet._observe_aux("robot-01", 19, report(5, 100500))
        assert memory.count("robot-01") == 0
        await pet._observe_aux("robot-01", 19, report(6, 100600))
        records = memory.recent("robot-01")
        assert [r.kind for r in records] == ["ambient_shift"]
        assert "pressure" in records[0].summary.lower()
        assert records[0].source_robot == "robot-01"
        assert records[0].witnessed is True
        assert memory.count("robot-02") == 0
        await pet._observe_aux("robot-01", 19, report(7, 0, valid=False))
        await pet._observe_aux("robot-01", 19, report(1, 101100))
        await pet._observe_aux("robot-01", 19, report(1, 101100))
        assert memory.count("robot-01") == 1
        await pet._observe_aux("robot-01", 19, report(2, 101600, age=2000))
        assert memory.count("robot-01") == 1
    finally:
        state.enabled = False
        await pet.close()


async def test_pet_drops_old_robot_frame_after_brief_peer_voice_turn(
    fleet, tmp_path,
):
    """A human on robot-02 supersedes robot-01's old scene even after VAD end."""
    from desk_robot.multimodal import MultimodalOrchestrator

    class NoOldSceneInference:
        def __init__(self):
            self.calls = 0

        async def compare(self, before, after):
            self.calls += 1
            raise AssertionError("Pre-human camera frame reached scene model")

    scene = NoOldSceneInference()
    memory = MemoryStore(tmp_path, [r.id for r in fleet.robots])
    pet = PetController(
        fleet, {"robot-01": ChangingCamera()},
        Conversation(fleet, GroundedChat(), SimulatedSpeaker(), memory=memory),
        memory, scene, interval=.05,
    )
    visual = MultimodalOrchestrator(
        fleet, {}, scene, asyncio.Lock(),
    )
    pet.multimodal = visual
    old_receipt = time.monotonic() - .25
    visual.hub.offer("robot-01", WHITE, old_receipt, source="proactive")
    visual.voice_started("robot-02")
    visual.voice_ended("robot-02")
    assert visual.latest_fleet_human_turn_at() > old_receipt
    state = pet.states["robot-01"]
    state.enabled = True
    state.quiet = True
    state.generation = 11
    worker = asyncio.create_task(pet._observe("robot-01", 11))
    try:
        await wait_for(lambda: state.stale_camera_events >= 1)
        assert scene.calls == 0
        assert memory.count("robot-01") == 0
        assert state.last_error is None
        assert state.enabled is True
    finally:
        state.enabled = False
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        await pet.close()
        await visual.close()
