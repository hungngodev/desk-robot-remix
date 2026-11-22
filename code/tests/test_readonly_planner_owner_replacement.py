"""Slow optional planner cannot use a replaced Mac voice owner."""

from types import SimpleNamespace

import pytest
from desk_robot.api_readonly_planner import register_readonly_planner_routes
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.mark.parametrize("replace_owner", (False, True))
def test_readonly_planner_rejects_reconnect_reusing_numeric_turn(
    settings, replace_owner,
):
    settings.mode = "hardware"
    previous = SimpleNamespace(
        _turn_epoch={"robot-01": 5},
        hub=SimpleNamespace(interaction_timeline=lambda *args, **kwargs: []),
    )
    runtime = SimpleNamespace(multimodal=previous)
    calls = []

    class Planner:
        async def readonly_tool_plan(self, messages):
            calls.append(messages)
            if replace_owner:
                # A new head session can begin at the same numeric epoch.
                # Old Ollama output cannot authorize its tool selections.
                runtime.multimodal = SimpleNamespace(
                    _turn_epoch={"robot-01": 5},
                    hub=SimpleNamespace(
                        interaction_timeline=lambda *args, **kwargs: [],
                    ),
                )
            return '{"tools":[{"route":"status"}]}'

    runtime.conversation = SimpleNamespace(chat=Planner())
    app = FastAPI()
    app.state.runtime = runtime
    register_readonly_planner_routes(
        app, settings, authorize=lambda: None,
    )
    with TestClient(app) as client:
        response = client.post(
            "/v1/pet/robot-01/plan-readonly",
            json={"transcript": "Please check your safety status"},
        )

    assert len(calls) == 1
    if replace_owner:
        assert response.status_code == 409
        assert "superseded" in response.json()["detail"]
        assert '"tools"' not in response.text
    else:
        assert response.status_code == 200
        assert response.json()["robot_id"] == "robot-01"
        assert response.json()["model_can_arm_motors"] is False
