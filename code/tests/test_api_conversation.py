import asyncio
from desk_robot.memory import MemoryStore

import pytest
from desk_robot.api import create_app
from desk_robot.conversation import Conversation
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
        assert client.post("/v1/robots/robot-01/explore", headers=tool).status_code == 403
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


async def test_five_robot_social_history_labels_observation_and_speech_correctly(settings, tmp_path):
    # Five distinct SQLite stores and personas; speech is not visual evidence.
    ids = ["robot-01", "robot-02", "robot-03", "robot-04", "robot-05"]
    settings.robots = [
        settings.robots[0].model_copy(update={"id": robot_id, "name": robot_id})
        for robot_id in ids
    ]
    memory = MemoryStore(tmp_path, ids)
    memory.remember(
        "robot-01", "camera_event", "A key appeared",
        kind="key", source_robot="robot-01", witnessed=True,
    )
    memory.remember(
        "robot-02", "camera_event", "A key appeared",
        kind="key", source_robot="robot-01", witnessed=False,
    )
    speaker = SimulatedSpeaker()
    c = Conversation(settings, SimulatedChat(), speaker, memory=memory)
    transcripts = await c.run(ids, "Describe a new game", 5)
    assert [line["robot_id"] for line in transcripts] == ids
    assert len(speaker.spoken) == 5
    assert "I witnessed: A key appeared" in c._persona_with_memory(settings.robots[0])
    assert "I was told by robot-01: A key appeared" in c._persona_with_memory(settings.robots[1])
    for robot_id in ids:
        records = memory.recent(robot_id)
        assert any(m.kind == "own_utterance" and m.source_robot == robot_id
                   and m.witnessed for m in records)
        assert sum(m.kind == "peer_utterance" and not m.witnessed for m in records) == 4
        assert memory.count(robot_id) == (6 if robot_id in ids[:2] else 5)
    context = c._persona_with_memory(settings.robots[1])
    assert "I said: " in context
    assert "I heard robot-01 say: " in context
    assert "I witnessed: I see a candy" not in context
    assert c.histories[ids[0]] is not c.histories[ids[1]]
