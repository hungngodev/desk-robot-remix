import asyncio
import json
from io import BytesIO

import httpx
import pytest
from PIL import Image
from desk_robot.api import create_app
from desk_robot.conversation import Conversation, OllamaChat
from desk_robot.memory import PetMemory
from desk_robot.pet import PetRuntime
from desk_robot.simulator import SimulatedChat, SimulatedSpeaker
from fastapi.testclient import TestClient


def test_model_token_cannot_enable_motion_or_manually_drive(settings, tokens):
    with TestClient(create_app(settings)) as client:
        assert client.get("/v1/robots").status_code == 401
        assert (
            client.get("/v1/robots", headers={b"Authorization": b"Bearer \xf1"}).status_code == 401
        )
        tool = {"Authorization": f"Bearer {tokens['DESK_ROBOT_TOOL_TOKEN']}"}
        operator = {"Authorization": f"Bearer {tokens['DESK_ROBOT_API_TOKEN']}"}
        assert client.get("/v1/robots", headers=tool).json()["mode"] == "simulation"
        assert client.post("/v1/robots/robot-01/enable", headers=tool).status_code == 403
        assert (
            client.post(
                "/v1/robots/robot-01/move", headers=tool, json={"command": "lift 90"}
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/v1/robots/robot-01/pickup", headers=tool, json={"target": "key"}
            ).status_code
            == 409
        )
        assert client.post("/v1/robots/robot-01/enable", headers=operator).status_code == 200
        result = client.post("/v1/robots/robot-01/pickup", headers=tool, json={"target": "key"})
        assert result.status_code == 202
        assert client.post("/v1/robots/robot-01/stop", headers=tool).status_code == 200
        assert (
            client.get(f"/v1/jobs/{result.json()['id']}", headers=tool).json()["state"]
            == "cancelled"
        )
        assert (
            client.post(
                "/v1/conversation",
                headers=tool,
                json={"robot_ids": ["robot-01", "robot-02"], "topic": "Hello", "utterances": 7},
            ).status_code
            == 422
        )


async def test_conversation_six_total_alternating_independent_histories(settings):
    speaker = SimulatedSpeaker()
    c = Conversation(settings, SimulatedChat(), speaker)
    result = await c.run(["robot-01", "robot-02"], "hello")
    assert len(result) == 6 and len(speaker.spoken) == 6
    assert [r["robot_id"] for r in result] == ["robot-01", "robot-02"] * 3
    assert c.histories["robot-01"] is not c.histories["robot-02"]
    assert any("said:" in entry["content"] for entry in c.histories["robot-02"])
    with pytest.raises(ValueError):
        await c.run(["robot-01", "robot-02"], "hello", 7)


async def test_unknown_robot_does_not_poison_future_conversation(settings):
    c = Conversation(settings, SimulatedChat(), SimulatedSpeaker())
    with pytest.raises(KeyError):
        await c.run(["robot-01", "wrong"], "hello")
    assert c.active is None
    assert len(await c.run(["robot-01", "robot-02"], "hello", 1)) == 1


async def test_conversation_cancellation_releases_session(settings):
    class SlowSpeaker(SimulatedSpeaker):
        async def say(self, robot, text):
            await asyncio.sleep(20)

    c = Conversation(settings, SimulatedChat(), SlowSpeaker())
    task = asyncio.create_task(c.run(["robot-01", "robot-02"], "hello"))
    await asyncio.sleep(0.01)
    with pytest.raises(RuntimeError, match="active"):
        await c.run(["robot-01", "robot-02"], "hello")
    await c.stop()
    assert task.cancelled() and c.active is None


def _jpeg(fill):
    im = Image.new("RGB", (120, 80), fill)
    out = BytesIO()
    im.save(out, "JPEG")
    return out.getvalue()


class _FrameHead:
    def __init__(self, frames):
        self.frames = iter(frames)

    async def snapshot(self):
        return next(self.frames)


class _RealEventObserver:
    def __init__(self):
        self.calls = 0

    async def observe_change(self, before, after):
        self.calls += 1
        return {"kind": "new_object", "summary": "A red object appeared", "confidence": 0.99}


async def test_pet_detects_confirmed_change_persists_memory_and_talks_once(settings, tmp_path):
    settings = settings.model_copy(update={"memory_dir": tmp_path})
    observer, speaker = _RealEventObserver(), SimulatedSpeaker()
    c = Conversation(settings, SimulatedChat(), speaker)
    head = _FrameHead([_jpeg("white"), _jpeg("red"), _jpeg("red")])
    memory = PetMemory(settings)
    pet = PetRuntime(settings, {"robot-01": head}, observer, c, memory)
    pet.states["robot-01"].enabled = True  # direct deterministic test, no background task
    try:
        assert await pet.observe_once("robot-01") is None
        assert await pet.observe_once("robot-01") is None
        result = await pet.observe_once("robot-01")
        assert result["spoken"] is True
        assert observer.calls == 1
        assert len(speaker.spoken) == 1
        entries = memory.recent("robot-01")
        assert len(entries) == 1 and entries[0]["observed_by"] == "robot-01"
        assert entries[0]["source"] == "camera"
        assert memory.recent("robot-02") == []
    finally:
        await pet.close()
    reopened = PetMemory(settings)
    try:
        assert reopened.recent("robot-01")[0]["summary"] == "A red object appeared"
    finally:
        reopened.close()


async def test_pet_quiet_and_peer_memory_are_not_firsthand(settings, tmp_path):
    settings = settings.model_copy(update={"memory_dir": tmp_path})
    observer, speaker = _RealEventObserver(), SimulatedSpeaker()
    memory = PetMemory(settings)
    pet = PetRuntime(
        settings, {"robot-01": _FrameHead([_jpeg("white"), _jpeg("blue"), _jpeg("blue")])},
        observer, Conversation(settings, SimulatedChat(), speaker), memory,
    )
    state = pet.states["robot-01"]
    state.enabled, state.quiet = True, True
    try:
        for _ in range(2):
            assert await pet.observe_once("robot-01") is None
        result = await pet.observe_once("robot-01")
        assert result["reason"] == "quiet"
        assert not speaker.spoken
        first = memory.recent("robot-01")[0]
        assert pet.share_with_peer(
            from_robot="robot-01", to_robot="robot-02", event_id=first["event_id"]
        )
        assert not pet.share_with_peer(
            from_robot="robot-01", to_robot="robot-02", event_id=first["event_id"]
        )
        peer = memory.recent("robot-02")[0]
        assert peer["source"] == "peer" and peer["observed_by"] == "robot-01"
        assert peer["told_by"] == "robot-01"
        assert '"secondhand": true' in memory.context("robot-02")
        with pytest.raises(ValueError, match="firsthand|Direct"):
            memory.remember("robot-02", event_id="fake", observed_by="robot-01",
                            kind="new_object", summary="I saw it", captured_at=1)
    finally:
        await pet.close()


async def test_pet_rejects_obsolete_vision_result_after_pause(settings, tmp_path):
    settings = settings.model_copy(update={"memory_dir": tmp_path})
    entered = asyncio.Event()
    release = asyncio.Event()

    class SlowObserver:
        async def observe_change(self, before, after):
            entered.set()
            await release.wait()
            return {"kind": "new_object", "summary": "An old event", "confidence": 0.99}

    memory = PetMemory(settings)
    speaker = SimulatedSpeaker()
    pet = PetRuntime(
        settings,
        {"robot-01": _FrameHead([_jpeg("white"), _jpeg("black"), _jpeg("black")])},
        SlowObserver(), Conversation(settings, SimulatedChat(), speaker), memory,
    )
    pet.states["robot-01"].enabled = True
    try:
        await pet.observe_once("robot-01")
        await pet.observe_once("robot-01")
        task = asyncio.create_task(pet.observe_once("robot-01"))
        await asyncio.wait_for(entered.wait(), 1)
        await pet.pause("robot-01")
        release.set()
        assert await task is None
        assert memory.recent("robot-01") == []
        assert speaker.spoken == []
    finally:
        await pet.close()


async def test_pet_all_five_share_one_spontaneous_floor(settings, tmp_path):
    settings = settings.model_copy(update={"memory_dir": tmp_path})
    speaker, observer = SimulatedSpeaker(), _RealEventObserver()
    memory = PetMemory(settings)
    heads = {
        r.id: _FrameHead([_jpeg("white"), _jpeg("black"), _jpeg("black")])
        for r in settings.robots
    }
    pet = PetRuntime(settings, heads, observer, Conversation(settings, SimulatedChat(), speaker), memory)
    try:
        for robot_id in heads:
            pet.states[robot_id].enabled = True
            await pet.observe_once(robot_id)
            await pet.observe_once(robot_id)
            result = await pet.observe_once(robot_id)
            assert result["spoken"] is (robot_id == next(iter(heads)))
        assert len(speaker.spoken) == 1
        for robot_id in heads:
            assert memory.recent(robot_id)[0]["source"] == "camera"
    finally:
        await pet.close()


async def test_ollama_vision_receives_two_real_images_and_rejects_ungrounded_answer(settings):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"message": {"content": (
            '{"kind":"new_object","summary":"A new key is visible","confidence":0.92}'
        )}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        settings = settings.model_copy(update={"ollama_vision_model": "local-vision"})
        chat = OllamaChat(settings, client)
        result = await chat.observe_change(_jpeg("white"), _jpeg("black"))
        assert result["summary"] == "A new key is visible"
        payload = json.loads(requests[0].content)
        assert len(payload["messages"][0]["images"]) == 2
        assert payload["model"] == "local-vision"


def test_pet_operator_api_requires_real_credential(settings, tokens, tmp_path):
    settings = settings.model_copy(update={"memory_dir": tmp_path})
    tool = {"Authorization": f"Bearer {tokens['DESK_ROBOT_TOOL_TOKEN']}"}
    operator = {"Authorization": f"Bearer {tokens['DESK_ROBOT_API_TOKEN']}"}
    with TestClient(create_app(settings)) as client:
        assert client.post("/v1/pet/robot-01/start", headers=tool).status_code == 403
        assert client.post("/v1/pet/robot-01/start", headers=operator).status_code == 200
        assert client.get("/v1/pet/robot-01", headers=tool).json()["enabled"] is True
        assert client.post("/v1/pet/robot-01/quiet", headers=operator,
                           json={"quiet": True}).json()["quiet"] is True
        assert client.post("/v1/pet/robot-01/pause", headers=operator).json()["enabled"] is False
