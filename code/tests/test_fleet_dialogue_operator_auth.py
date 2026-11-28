"""A Xiaozhi tool credential cannot claim human initiated fleet dialogue."""
import pytest
from desk_robot.api import create_app
from desk_robot.conversation import Conversation
from desk_robot.simulator import SimulatedChat, SimulatedSpeaker
from fastapi.testclient import TestClient


def test_tool_credential_cannot_preempt_fleet_or_claim_operator_origin(
    settings, tokens, monkeypatch,
):
    app = create_app(settings)
    with TestClient(app) as client:
        calls = []

        async def interrupt(robot_id):
            calls.append(("interrupt", robot_id))

        async def run(robot_ids, topic, utterances):
            calls.append(("run", tuple(robot_ids), topic, utterances))
            return [{"robot_id": robot_ids[0], "text": "Hello"}]

        monkeypatch.setattr(app.state.runtime.pet, "interrupt", interrupt)
        monkeypatch.setattr(app.state.runtime.conversation, "run", run)
        body = {
            "robot_ids": ["robot-01", "robot-02"],
            "topic": "Start a two-pet chat", "utterances": 2,
        }
        tool = {"Authorization": f"Bearer {tokens['DESK_ROBOT_TOOL_TOKEN']}"}
        human = {"Authorization": f"Bearer {tokens['DESK_ROBOT_API_TOKEN']}"}
        denied = client.post("/v1/conversation", json=body, headers=tool)
        assert denied.status_code == 403
        assert calls == []  # No fleet speech or pet interruption.
        allowed = client.post("/v1/conversation", json=body, headers=human)
        assert allowed.status_code == 200
        assert allowed.json()["transcript"][0]["text"] == "Hello"
        assert calls[-1] == (
            "run", ("robot-01", "robot-02"), "Start a two-pet chat", 2,
        )
        assert sum(row[0] == "interrupt" for row in calls) == len(settings.robots)


@pytest.mark.parametrize(("sharing", "social", "callback"), [
    (False, False, True),
    (True, False, True),
    (True, True, False),
])
async def test_direct_hardware_social_requires_all_grants(settings, sharing, social, callback):
    settings.mode = "hardware"
    settings.fleet_text_sharing_enabled = sharing
    settings.fleet_social_autonomy_enabled = social
    speaker = SimulatedSpeaker()
    agent = Conversation(settings, SimulatedChat(), speaker)
    with pytest.raises(RuntimeError, match="Group conversation consent revoked"):
        await agent.run(
            ["robot-01", "robot-02"], "Peer chat", 2,
            origin="autonomous_social",
            permission_check=(lambda: True) if callback else None,
        )
    assert agent.active is None
    assert agent.histories == {}
    assert not speaker.spoken
