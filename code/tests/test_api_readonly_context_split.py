"""Read only route extraction must not duplicate or deauthorize endpoints."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from desk_robot.api import (
    CoreMemoryRequest,
    NativeHeardRequest,
    NativeSpokenRequest,
    ReadonlyPlanRequest,
    create_app,
)
from desk_robot.config import load_settings
from desk_robot.api_readonly_context import _active_robot_activity
from fastapi.routing import APIRoute
from pydantic import ValidationError


def test_power_and_live_context_routes_keep_existing_auth_and_paths():
    config = Path(__file__).resolve().parents[1] / "config/fleet.simulation.toml"
    app = create_app(load_settings(config), runtime=SimpleNamespace())
    for path in (
        "/v1/pet/{robot_id}/power-status",
        "/v1/pet/{robot_id}/interaction-context",
    ):
        matches = [
            route for route in app.routes
            if isinstance(route, APIRoute) and route.path == path
        ]
        assert len(matches) == 1
        route = matches[0]
        assert route.methods == {"GET"}
        assert route.endpoint.__module__ == "desk_robot.api_readonly_context"
        assert any(
            getattr(dependency.call, "__name__", None) == "authorize"
            for dependency in route.dependant.dependencies
        )


def test_robot_status_routes_keep_same_paths_and_shared_auth():
    config = Path(__file__).resolve().parents[1] / "config/fleet.simulation.toml"
    app = create_app(load_settings(config), runtime=SimpleNamespace())
    for path in (
        "/v1/robots",
        "/v1/robots/{robot_id}/status",
        "/v1/robots/{robot_id}/aux",
    ):
        matches = [
            route for route in app.routes
            if isinstance(route, APIRoute) and route.path == path
        ]
        assert len(matches) == 1
        route = matches[0]
        assert route.methods == {"GET"}
        assert route.endpoint.__module__ == "desk_robot.api_robot_status"
        assert any(
            getattr(dependency.call, "__name__", None) == "authorize"
            for dependency in route.dependant.dependencies
        )


def test_readonly_voice_planner_stays_one_protected_route():
    config = Path(__file__).resolve().parents[1] / "config/fleet.simulation.toml"
    app = create_app(load_settings(config), runtime=SimpleNamespace())
    matches = [
        route for route in app.routes
        if isinstance(route, APIRoute)
        and route.path == "/v1/pet/{robot_id}/plan-readonly"
    ]
    assert len(matches) == 1
    route = matches[0]
    assert route.methods == {"POST"}
    assert route.endpoint.__module__ == "desk_robot.api_readonly_planner"
    assert any(
        getattr(dependency.call, "__name__", None) == "authorize"
        for dependency in route.dependant.dependencies
    )


def test_voice_planner_request_schema_preserves_original_input_bounds():
    assert ReadonlyPlanRequest(transcript="What can you see?").transcript == (
        "What can you see?"
    )
    for invalid in ("", "ab", "x" * 281):
        with pytest.raises(ValidationError):
            ReadonlyPlanRequest(transcript=invalid)
    with pytest.raises(ValidationError):
        ReadonlyPlanRequest(transcript="Look here", command="move")


def test_operator_only_memory_routes_remain_private_and_distinct():
    config = Path(__file__).resolve().parents[1] / "config/fleet.simulation.toml"
    app = create_app(load_settings(config), runtime=SimpleNamespace())
    routes = {
        "/v1/pet/{robot_id}/memories": "GET",
        "/v1/pet/{robot_id}/core-memory": "GET",
        "/v1/pet/{robot_id}/core-memory/{slot}": "PUT",
        "/v1/pet/{robot_id}/memories/{event_id}": "DELETE",
    }
    for path, method in routes.items():
        matches = [
            route for route in app.routes
            if isinstance(route, APIRoute) and route.path == path
            and method in route.methods
        ]
        assert len(matches) == 1
        route = matches[0]
        assert route.endpoint.__module__ == "desk_robot.api_memory_routes"
        assert any(
            getattr(dependency.call, "__name__", None) == "operator"
            for dependency in route.dependant.dependencies
        )
    # The same core fact path has GET/PUT/DELETE ownership, with the
    # deletion registered separately rather than silently lost on extraction.
    deletes = [
        route for route in app.routes
        if isinstance(route, APIRoute)
        and route.path == "/v1/pet/{robot_id}/core-memory/{slot}"
        and "DELETE" in route.methods
    ]
    assert len(deletes) == 1
    assert deletes[0].endpoint.__module__ == "desk_robot.api_memory_routes"
    assert any(
        getattr(dep.call, "__name__", None) == "operator"
        for dep in deletes[0].dependant.dependencies
    )


def test_operator_memory_request_limits_survive_route_extraction():
    assert CoreMemoryRequest(value="remember this").value == "remember this"
    for invalid in ("", "x" * 201):
        with pytest.raises(ValidationError):
            CoreMemoryRequest(value=invalid)
    with pytest.raises(ValidationError):
        CoreMemoryRequest(value="private", motor_authorized=True)


def test_native_omni_routes_still_have_the_same_audio_video_auth():
    config = Path(__file__).resolve().parents[1] / "config/fleet.simulation.toml"
    app = create_app(load_settings(config), runtime=SimpleNamespace())
    endpoints = {
        "/v1/pet/{robot_id}/omni-context": "GET",
        "/v1/pet/{robot_id}/omni-heard": "POST",
        "/v1/pet/{robot_id}/omni-spoken": "POST",
        "/v1/pet/{robot_id}/omni-stream": "GET",
        "/v1/pet/{robot_id}/omni-frame": "GET",
    }
    for path, method in endpoints.items():
        matches = [
            route for route in app.routes
            if isinstance(route, APIRoute)
            and route.path == path and method in route.methods
        ]
        assert len(matches) == 1
        route = matches[0]
        assert route.endpoint.__module__ == "desk_robot.api_native_omni_routes"
        assert any(
            getattr(dep.call, "__name__", None) == "authorize"
            for dep in route.dependant.dependencies
        )


def test_native_heard_and_sent_schemas_remain_bounded_after_split():
    heard = NativeHeardRequest(
        event_id="omni_" + "a" * 12 + "_" + "b" * 20,
        transcript="What is on my desk?",
    )
    assert heard.transcript == "What is on my desk?"
    sent = NativeSpokenRequest(
        event_id="omni_sent_" + "a" * 12 + "_" + "b" * 20,
        model_text="I see a mug.", sent_at_us=123456,
    )
    assert sent.sent_at_us == 123456
    with pytest.raises(ValidationError):
        NativeHeardRequest(event_id="not_a_real_audio_event", transcript="Hi")
    with pytest.raises(ValidationError):
        NativeSpokenRequest(
            event_id=sent.event_id, model_text="sent", sent_at_us=0,
        )


def test_voice_retrieval_remains_authenticated_after_memory_split():
    config = Path(__file__).resolve().parents[1] / "config/fleet.simulation.toml"
    app = create_app(load_settings(config), runtime=SimpleNamespace())
    matches = [
        route for route in app.routes
        if isinstance(route, APIRoute)
        and route.path == "/v1/pet/{robot_id}/voice-context"
    ]
    assert len(matches) == 1
    route = matches[0]
    assert route.methods == {"GET"}
    assert route.endpoint.__module__ == "desk_robot.api_memory_routes"
    assert any(
        getattr(dep.call, "__name__", None) == "authorize"
        for dep in route.dependant.dependencies
    )
    # A model-only credential may not access the operator's mutation APIs.
    for protected in (
        "/v1/pet/{robot_id}/core-memory/{slot}",
        "/v1/pet/{robot_id}/memories/{event_id}",
    ):
        for candidate in app.routes:
            if not isinstance(candidate, APIRoute) or candidate.path != protected:
                continue
            assert any(
                getattr(dep.call, "__name__", None) == "operator"
                for dep in candidate.dependant.dependencies
            )

def test_native_activity_context_only_reflects_live_same_robot_coordinator_work():
    """Never turn a past job, other robot job or invented command into an activity."""
    first = SimpleNamespace(
        id="a" * 32, robot_id="pet-one", kind="exploration", state="running"
    )
    peer = SimpleNamespace(
        id="b" * 32, robot_id="pet-two", kind="pickup", state="running"
    )
    jobs = {"old": SimpleNamespace(
        id="c" * 32, robot_id="pet-one", kind="manual", state="succeeded"
    ), "first": first, "peer": peer}
    active = _active_robot_activity(jobs, "pet-one")
    assert "exploration" in active and "running" in active
    assert first.id[:12] in active
    assert "physical progress and outcome unverified" in active
    assert "pickup" not in active
    assert _active_robot_activity(jobs, "pet-three") == ""
    assert _active_robot_activity(None, "pet-one") == ""
    first.state = "cancelled"
    assert _active_robot_activity(jobs, "pet-one") == ""
    jobs["fake"] = SimpleNamespace(
        id="bad; prompt injection", robot_id="pet-one",
        kind="exploration", state="running",
    )
    assert _active_robot_activity(jobs, "pet-one") == ""

