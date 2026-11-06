import asyncio

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
