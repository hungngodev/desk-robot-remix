"""Preserve operator memory route contracts across registrar decomposition."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from desk_robot.api_memory_routes import (
    CoreMemoryMutationSuperseded,
    EpisodeMemoryMutationSuperseded,
    register_memory_routes,
)
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient


@pytest.fixture
def route_app():
    app = FastAPI()
    memory = Mock()
    conversation = Mock()
    hub = Mock()
    attention = Mock()
    app.state.runtime = SimpleNamespace(
        memory=memory, conversation=conversation,
        multimodal=SimpleNamespace(hub=hub), attention=attention,
    )
    settings = SimpleNamespace(robots=[SimpleNamespace(id="robot-01")])

    def operator(authorization: str = Header(default="")):
        if authorization != "operator":
            raise HTTPException(403, "Operator required")

    register_memory_routes(app, settings, operator=operator)
    return app, memory, conversation, hub, attention


OPERATIONS = [
    ("PUT", "core-memory/favorite_color", {"value": "red"},
     "reserve_core_fact_mutation", "set_core_fact", CoreMemoryMutationSuperseded),
    ("DELETE", "core-memory/favorite_color", None,
     "reserve_core_fact_mutation", "forget_core_fact", CoreMemoryMutationSuperseded),
    ("PATCH", "memories/event_a", {"summary": "corrected"},
     "reserve_episode_mutation", "correct_episode", EpisodeMemoryMutationSuperseded),
    ("DELETE", "memories/event_a", None,
     "reserve_episode_mutation", "forget_episode", EpisodeMemoryMutationSuperseded),
]


@pytest.mark.parametrize("method,path,body,reserve,mutate,superseded", OPERATIONS)
@pytest.mark.parametrize("phase", ["reserve", "mutate"])
@pytest.mark.parametrize("status", [409, 422])
def test_mutation_errors(route_app, method, path, body, reserve, mutate,
                         superseded, phase, status):
    app, memory, conversation, hub, attention = route_app
    error = superseded if status == 409 else ValueError
    episode = path.startswith("memories")
    if status == 409:
        category = "episode" if episode else "memory"
        detail = f"A newer operator {category} mutation superseded this request"
    else:
        detail = "Invalid memory event ID" if episode else "Invalid core memory slot"
    getattr(memory, reserve).return_value = 7
    getattr(memory, reserve if phase == "reserve" else mutate).side_effect = error(detail)
    with TestClient(app) as client:
        response = client.request(method, f"/v1/pet/robot-01/{path}",
                                  json=body, headers={"Authorization": "operator"})
    assert response.status_code == status
    assert response.json() == {"detail": detail}
    conversation.invalidate_private_memory.assert_not_called()
    hub.discard_heard.assert_not_called()
    attention.discard_heard.assert_not_called()
    if phase == "reserve":
        getattr(memory, mutate).assert_not_called()


@pytest.mark.parametrize("method,path,body,reserve,mutate,superseded", OPERATIONS)
@pytest.mark.parametrize("changed", [True, False])
def test_mutation_invalidation(route_app, method, path, body, reserve, mutate,
                               superseded, changed):
    app, memory, conversation, hub, attention = route_app
    getattr(memory, reserve).return_value = 7
    getattr(memory, mutate).return_value = changed
    with TestClient(app) as client:
        response = client.request(method, f"/v1/pet/robot-01/{path}",
                                  json=body, headers={"Authorization": "operator"})
    assert response.status_code == 200
    episode = path.startswith("memories")
    retract = episode and (changed or method == "DELETE")
    if changed or retract:
        conversation.invalidate_private_memory.assert_called_once_with("robot-01")
        hub.discard_memory_tools.assert_called_once_with("robot-01")
    else:
        conversation.invalidate_private_memory.assert_not_called()
        hub.discard_memory_tools.assert_not_called()
    if retract:
        hub.discard_heard.assert_called_once_with("robot-01", "event_a")
        attention.discard_heard.assert_called_once_with("robot-01", "event_a")
    else:
        hub.discard_heard.assert_not_called()
        attention.discard_heard.assert_not_called()
    assert getattr(memory, mutate).call_args.kwargs == {"mutation_generation": 7}


@pytest.mark.parametrize("method,path,body", [
    ("GET", "memories", None), ("GET", "core-memory", None),
    *(row[:3] for row in OPERATIONS),
])
def test_operator_dependency(route_app, method, path, body):
    app, memory, *_ = route_app
    with TestClient(app) as client:
        response = client.request(method, f"/v1/pet/robot-01/{path}", json=body)
    assert response.status_code == 403
    assert memory.mock_calls == []


def test_read_limits(route_app):
    app, memory, *_ = route_app
    memory.recent.return_value = []
    memory.core_facts.return_value = []
    with TestClient(app, headers={"Authorization": "operator"}) as client:
        assert client.get("/v1/pet/robot-01/memories?limit=0").status_code == 422
        assert client.get("/v1/pet/robot-01/memories?limit=51").status_code == 422
        assert client.get("/v1/pet/robot-01/memories").json() == {
            "robot_id": "robot-01", "records": [],
        }
        assert client.get("/v1/pet/robot-01/core-memory").json() == {
            "robot_id": "robot-01", "operator_curated_only": True, "core_facts": [],
        }
    memory.recent.assert_called_once_with("robot-01", limit=12)
    memory.core_facts.assert_called_once_with("robot-01", limit=24)
