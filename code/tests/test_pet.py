"""Proactive pet runtime tests: simulation and host only, never physical evidence."""

import asyncio
import json
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from desk_robot.api import create_app
from desk_robot.config import load_settings
from desk_robot.conversation import Conversation
from desk_robot.memory import MemoryStore
from desk_robot.pet import PetController
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
        await wait_for(lambda: head.calls >= 7)
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
