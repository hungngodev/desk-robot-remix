"""Read only route extraction must not duplicate or deauthorize endpoints."""
from pathlib import Path
from types import SimpleNamespace

from fastapi.routing import APIRoute

from desk_robot.api import create_app
from desk_robot.config import load_settings


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
    import pytest
    from pydantic import ValidationError

    from desk_robot.api import ReadonlyPlanRequest

    assert ReadonlyPlanRequest(transcript="What can you see?").transcript == (
        "What can you see?"
    )
    for invalid in ("", "ab", "x" * 281):
        with pytest.raises(ValidationError):
            ReadonlyPlanRequest(transcript=invalid)
    with pytest.raises(ValidationError):
        ReadonlyPlanRequest(transcript="Look here", command="move")
