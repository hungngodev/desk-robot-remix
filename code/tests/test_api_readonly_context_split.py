"""Read only route extraction must not duplicate or deauthorize endpoints."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from desk_robot.api import CoreMemoryRequest, ReadonlyPlanRequest, create_app
from desk_robot.config import load_settings
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
