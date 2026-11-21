"""An explicit visual read-only plan belongs to its original camera grant."""

import json
from types import SimpleNamespace

import pytest
from desk_robot.api import create_app
from fastapi.testclient import TestClient


@pytest.mark.parametrize(
    "initial,transition,model_route,transcript,expected_status,expected_routes",
    [
        (True, "none", "look", "Please look at my desk", 200, ["look"]),
        (True, "revoke_regrant", "look", "Please look at my desk", 409, None),
        (True, "revoke", "look", "Please look at my desk", 403, None),
        (False, "grant", "look", "Please look at my desk", 409, None),
        (False, "none", "look", "Please look at my desk", 200, []),
        (True, "revoke_regrant", "status", "What is your safety status?", 200, ["status"]),
    ],
)
def test_readonly_look_cannot_survive_camera_grant_change_without_frames(
    settings, tokens, initial, transition, model_route, transcript,
    expected_status, expected_routes,
):
    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = initial
    robot_id = settings.robots[0].id

    class Model:
        async def reply(self, _history):
            # The real model can finish after consent is revoked; this fake
            # changes the same Settings object during the awaited reply.
            if transition in {"revoke", "revoke_regrant"}:
                settings.voice_vision_tools_enabled = False
            if transition in {"grant", "revoke_regrant"}:
                settings.voice_vision_tools_enabled = True
            return json.dumps({"tools": [{"route": model_route}]})

    async def noop():
        pass

    runtime = SimpleNamespace(
        conversation=SimpleNamespace(chat=Model()),
        multimodal=None,
        start=noop,
        close=noop,
    )
    headers = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with TestClient(create_app(settings, runtime=runtime)) as client:
        response = client.post(
            f"/v1/pet/{robot_id}/plan-readonly",
            headers=headers, json={"transcript": transcript},
        )
    assert response.status_code == expected_status
    if expected_routes is not None:
        assert [item["route"] for item in response.json()["tools"]] == expected_routes
        assert response.json()["motor_authorized"] is False
        assert response.json()["charging_authorized"] is False


@pytest.mark.parametrize(
    "question,expected",
    [
        ("How many days until my exam?", []),
        ("What size battery should I buy?", []),
        ("What shape should my future robot be?", []),
        ("What color is my favorite book cover?", []),
        ("How many keys are on my desk?", ["look"]),
        ("What color is the mug in front of you?", ["look"]),
        ("What color is this?", ["look"]),
        ("Please look at the mug", ["look"]),
    ],
)
def test_readonly_visual_quantifier_requires_scene_referent(
    settings, tokens, question, expected,
):
    """A model cannot turn unrelated number/size questions into a camera call."""
    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    robot_id = settings.robots[0].id

    class OvereagerModel:
        async def reply(self, _history):
            return json.dumps({"tools": [{"route": "look"}]})

    async def noop():
        pass

    runtime = SimpleNamespace(
        conversation=SimpleNamespace(chat=OvereagerModel()),
        multimodal=None,
        start=noop,
        close=noop,
    )
    headers = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with TestClient(create_app(settings, runtime=runtime)) as client:
        response = client.post(
            f"/v1/pet/{robot_id}/plan-readonly",
            headers=headers, json={"transcript": question},
        )
    assert response.status_code == 200
    assert [item["route"] for item in response.json()["tools"]] == expected
    assert response.json()["motor_authorized"] is False
