"""Mac API to authenticated Sense to WROOM pose read-only contract replay."""

from types import SimpleNamespace

import httpx
from desk_robot.api import create_app
from desk_robot.transport import HttpHead
from fastapi.testclient import TestClient


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
        assert client.get(route).status_code == 403
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


def test_readonly_pose_old_firmware_returns_501_without_breaking_status(settings, tokens):
    robot = settings.robots[0]
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/api/pose":
            return httpx.Response(501)
        assert request.url.path == "/api/status"
        return httpx.Response(200, json={"robot_id": robot.id, "armed": False})

    client, commands, head = _client(settings, handler)
    auth = {"Authorization": "Bearer " + tokens["DESK_ROBOT_API_TOKEN"]}
    with client:
        response = client.get(f"/v1/robots/{robot.id}/pose", headers=auth)
        assert response.status_code == 501
        assert "unsupported" in response.json()["detail"].lower()
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
