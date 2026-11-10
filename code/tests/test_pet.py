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
            "force": {"adc": [pressure, 0], "valid": True, "calibrated": False},
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
        "force": {"adc": [30000, 30000], "valid": True, "calibrated": False},
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
            "force": {"adc": [0, 0], "valid": False, "calibrated": False},
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
        assert memory.count("robot-02") == 0
        await pet._observe_optional("robot-01", 4, {"extras": extra(0, False, 12)})
        await pet._observe_optional("robot-01", 4, {"extras": extra(0, True, 15)})
        await pet._observe_optional("robot-01", 4, {"extras": extra(2, True, 16)})
        assert sum(m.kind == "petting_zone" for m in memory.recent("robot-01")) == 2
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
