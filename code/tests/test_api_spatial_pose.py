"""Mac API to authenticated Sense to WROOM pose read-only contract replay."""

import sqlite3
from types import SimpleNamespace

import httpx
import pytest
from desk_robot.api import create_app
from desk_robot.api_spatial_pose import NavigateRequest, register_spatial_pose_route
from desk_robot.transport import HttpHead
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import ValidationError


def _client(settings, handler):
    robot = settings.robots[0]
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    head = HttpHead(robot, http)
    sent_commands = []

    async def forbidden_command(command):
        sent_commands.append(command)
        raise AssertionError("Pose observation must never dispatch a command")

    head.command = forbidden_command

    async def noop_start():
        pass

    async def close():
        await http.aclose()

    runtime = SimpleNamespace(
        coordinator=SimpleNamespace(
            robot=lambda robot_id: settings.robot(robot_id),
            heads={robot.id: head},
        ),
        start=noop_start,
        close=close,
    )
    return TestClient(create_app(settings, runtime=runtime)), sent_commands, head


def test_readonly_pose_operator_route_preserves_source_and_never_arms(settings, tokens):
    robot = settings.robots[0]
    calls = []

    def handler(request):
        assert request.headers["Authorization"] == (
            "Bearer " + tokens[robot.token_env]
        )
        assert request.method == "GET"
        assert request.url.path == "/api/pose"
        calls.append(request.url.path)
        seq = len(calls)
        return httpx.Response(200, json={
            "robot_id": robot.id, "v": 1, "body_boot": 41,
            "origin": 3, "seq": seq, "sample_us": seq * 100_000,
            "x_mm": 25, "y_mm": -10, "yaw_mrad": 300,
            "quality": "valid", "head_boot": 99,
        })

    client, commands, head = _client(settings, handler)
    route = f"/v1/robots/{robot.id}/pose"
    operator = {"Authorization": "Bearer " + tokens["DESK_ROBOT_API_TOKEN"]}
    tool = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with client:
        assert client.get(route).status_code == 401
        assert client.get(route, headers=tool).status_code == 403
        baseline = client.get(route, headers=operator)
        assert baseline.status_code == 200
        assert baseline.json()["local_odometry_continuous"] is False
        fresh = client.get(route, headers=operator)
        assert fresh.status_code == 200
        data = fresh.json()
        assert data["pose"]["seq"] == 2
        assert data["pose"]["head_boot"] == 99
        assert data["pose"]["y_mm"] == -10
        assert data["local_odometry_continuous"] is True
        assert data["needs_reanchor"] is True
        assert data["map_anchored"] is False
        for field in ("navigation_authorized", "motor_authorized",
                      "charging_authorized", "physical_acceptance_pass"):
            assert data[field] is False
        assert head.pose_fence.needs_reanchor
    assert calls == ["/api/pose", "/api/pose"]
    assert commands == []


@pytest.mark.parametrize(
    ("fault", "status_code"),
    [
        ("http404", 501), ("http501", 501), ("v0", 501), ("v2", 501),
        ("missing_version", 503), ("bool_version", 503), ("foreign_version", 503),
    ],
)
def test_readonly_pose_old_firmware_returns_501_without_breaking_status(
    settings, tokens, fault, status_code,
):
    robot = settings.robots[0]
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/api/pose":
            if fault.startswith("http"):
                return httpx.Response(int(fault[4:]))
            packet = {"robot_id": robot.id}
            if fault == "foreign_version":
                packet.update(robot_id="foreign-robot", v=0)
            elif fault != "missing_version":
                packet["v"] = {"v0": 0, "v2": 2, "bool_version": True}[fault]
            return httpx.Response(200, json=packet)
        assert request.url.path == "/api/status"
        return httpx.Response(200, json={"robot_id": robot.id, "armed": False})

    client, commands, head = _client(settings, handler)
    auth = {"Authorization": "Bearer " + tokens["DESK_ROBOT_API_TOKEN"]}
    with client:
        response = client.get(f"/v1/robots/{robot.id}/pose", headers=auth)
        assert response.status_code == status_code
        if status_code == 501:
            assert "unsupported" in response.json()["detail"].lower()
            assert head.pose_fence.blocked_reason == "pose_unsupported"
        assert head.pose_fence.current(1) is None
        status = client.get(f"/v1/robots/{robot.id}/status", headers=auth)
        assert status.status_code == 200
        assert status.json()["armed"] is False
    assert calls == ["/api/pose", "/api/status"]
    assert commands == []


def test_readonly_pose_replay_and_foreign_robot_fail_closed(settings, tokens):
    robot = settings.robots[0]
    packet = {
        "robot_id": robot.id, "v": 1, "body_boot": 3, "origin": 2,
        "seq": 1, "sample_us": 100_000, "x_mm": 0, "y_mm": 0,
        "yaw_mrad": 0, "quality": "valid",
    }
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, json={**packet, "robot_id": "robot-foreign"})
        return httpx.Response(200, json=packet)

    client, commands, head = _client(settings, handler)
    auth = {"Authorization": "Bearer " + tokens["DESK_ROBOT_API_TOKEN"]}
    path = f"/v1/robots/{robot.id}/pose"
    with client:
        assert client.get(path, headers=auth).status_code == 503
        assert client.get(path, headers=auth).status_code == 200
        assert client.get(path, headers=auth).status_code == 503
        assert head.pose_fence.current(1) is None
    assert commands == []


def test_readonly_pose_unqualified_source_never_looks_map_anchored(settings, tokens):
    robot = settings.robots[0]
    seq = 0

    def handler(request):
        nonlocal seq
        seq += 1
        return httpx.Response(200, json={
            "robot_id": robot.id, "v": 1, "body_boot": 9,
            "origin": 0, "seq": seq, "sample_us": seq * 100_000,
            "x_mm": 0, "y_mm": 0, "yaw_mrad": 0,
            "quality": "unavailable",
        })

    client, commands, _ = _client(settings, handler)
    auth = {"Authorization": "Bearer " + tokens["DESK_ROBOT_API_TOKEN"]}
    with client:
        result = client.get(f"/v1/robots/{robot.id}/pose", headers=auth)
        assert result.status_code == 200
        assert result.json()["pose"]["quality"] == "unavailable"
        assert result.json()["local_odometry_continuous"] is False
        assert result.json()["navigation_authorized"] is False
        assert result.json()["map_anchored"] is False
    assert commands == []

def test_pose_route_registration_is_unique_and_operator_only(settings, tokens):
    """Never let a tool-token route shadow the established operator route."""
    robot = settings.robots[0]
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        assert request.headers["Authorization"] == "Bearer " + tokens[robot.token_env]
        return httpx.Response(200, json={
            "robot_id": robot.id, "v": 1, "body_boot": 41,
            "origin": 3, "seq": 1, "sample_us": 100_000,
            "x_mm": 25, "y_mm": -10, "yaw_mrad": 300,
            "quality": "valid", "head_boot": 99,
        })

    client, commands, _ = _client(settings, handler)
    routes = [
        route for route in client.app.routes
        if isinstance(route, APIRoute)
        and route.path == "/v1/robots/{robot_id}/pose"
    ]
    assert len(routes) == 1
    assert routes[0].methods == {"GET"}

    path = f"/v1/robots/{robot.id}/pose"
    operator = {"Authorization": "Bearer " + tokens["DESK_ROBOT_API_TOKEN"]}
    tool = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with client:
        assert client.get(path).status_code == 401
        assert client.get(path, headers=tool).status_code == 403
        assert client.post(path, headers=operator).status_code == 405
        assert calls == []

        result = client.get(path, headers=operator)
        assert result.status_code == 200
        data = result.json()
        assert data["robot_id"] == robot.id
        assert data["pose"]["seq"] == 1
        assert data["motor_authorized"] is False
        assert data["navigation_authorized"] is False
    assert calls == [("GET", "/api/pose")]
    assert commands == []

def test_readonly_pose_missing_head_adapter_fails_closed(settings, tokens):
    """A temporarily absent head is a 503, never an HTTP 500 or fake odometry."""
    robot = settings.robots[0]
    requests = []

    def forbidden_request(request):
        requests.append(request.url.path)
        raise AssertionError("Missing head must not issue physical transport I/O")

    client, commands, _ = _client(settings, forbidden_request)
    route = f"/v1/robots/{robot.id}/pose"
    operator = {"Authorization": "Bearer " + tokens["DESK_ROBOT_API_TOKEN"]}
    tool = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    with client:
        client.app.state.runtime.coordinator.heads.pop(robot.id)
        assert client.get(route, headers=tool).status_code == 403
        result = client.get(route, headers=operator)
        assert result.status_code == 503
        assert result.json() == {"detail": "Pose head unavailable"}
    assert requests == []
    assert commands == []


@pytest.mark.parametrize(
    ("failure", "status"),
    [
        (None, 200),
        ("sqlite", 503),
        ("disk", 503),
        ("consent", 403),
        ("forget", 409),
        ("origin", 409),
        ("foreign", 503),
        ("query", 400),
    ],
)
def test_spatial_memory_read_fences_and_safe_errors(failure, status):
    app = FastAPI()
    settings = SimpleNamespace(
        mode="hardware", voice_memory_tools_enabled=True,
        voice_memory_consent_generation=1,
    )
    state = SimpleNamespace(epoch=1, body_boot=7, origin_id="odom-1")
    conversation = SimpleNamespace(_private_memory_generation={"robot-01": 0})

    def recall(robot_id, object_key):
        if failure == "sqlite":
            raise sqlite3.OperationalError("database locked at /private/robot-01.db")
        if failure == "disk":
            raise OSError("private database path")
        if failure == "query":
            raise ValueError("private database path")
        if failure == "consent":
            settings.voice_memory_consent_generation += 1
        if failure == "forget":
            conversation._private_memory_generation[robot_id] += 1
        if failure == "origin":
            state.epoch += 1
        return {
            "robot_id": "robot-02" if failure == "foreign" else robot_id,
            "object_key": object_key,
            "status": "unknown",
            "navigation_authorized": False,
        }

    owner = SimpleNamespace(state=lambda _: state, recall_memory=recall)
    app.state.runtime = SimpleNamespace(spatial=owner, conversation=conversation)
    register_spatial_pose_route(
        app,
        operator=lambda: None,
        coordinator=lambda: SimpleNamespace(robot=lambda _: None),
        settings=settings,
    )
    with TestClient(app) as client:
        response = client.get("/v1/robots/robot-01/spatial/memory?object_key=key")
    assert response.status_code == status
    assert "private database path" not in response.text
    assert "/private/" not in response.text
    if status == 200:
        assert response.json()["navigation_authorized"] is False
    else:
        assert "object_key" not in response.json()


@pytest.mark.parametrize("field,value", [
    ("goal", [True, 0]), ("goal", [-1, 0]), ("goal", [64, 0]),
    ("goal", [0.0, 1]), ("goal", ["1", 0]), ("goal", [0]),
    ("goal", [0, 1, 2]), ("start", [0, float("nan")]),
    ("start", [0, float("inf")]), ("heading", True),
    ("heading", -1), ("goal_heading", 4), ("goal_heading", 1.0),
])
def test_invalid_navigation_input(field, value):
    with pytest.raises(ValidationError):
        NavigateRequest.model_validate({field: value})


def test_navigation_request_is_an_immutable_snapshot():
    source = [0, 63]
    request = NavigateRequest.model_validate({"goal": source, "heading": 0, "goal_heading": 3})
    source[0] = 17
    assert request.goal == (0, 63)
    for name, value in (("goal", (True, 0)), ("heading", 99), ("label", "changed")):
        with pytest.raises(ValidationError, match="frozen"):
            setattr(request, name, value)
    assert request.goal == (0, 63)
    assert request.heading == 0
    assert request.label is None
