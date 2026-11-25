"""Read-only status endpoints distinguish absent adapters from raw evidence."""

from types import SimpleNamespace

import pytest
from desk_robot.api_robot_status import register_robot_status_routes
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _status_client(heads):
    app = FastAPI()
    heard = []
    owner = SimpleNamespace(robot=lambda _: None, heads=heads)
    register_robot_status_routes(
        app, SimpleNamespace(mode="hardware", robots=[]),
        authorize=lambda: None, coordinator=lambda: owner,
        requested_tool_context=lambda request, robot_id: object(),
        remember_tool_context=lambda *args: heard.append(args),
        current_tool_context=lambda *args: None,
    )
    return TestClient(app, raise_server_exceptions=False), heard


@pytest.mark.parametrize("route", ["status", "aux"])
def test_missing_head_returns_unavailable_not_internal_error(route):
    client, heard = _status_client({})
    with client:
        result = client.get(f"/v1/robots/robot-01/{route}")
    assert result.status_code == 503
    assert result.json() == {"detail": "Telemetry head unavailable"}
    assert heard == []


def test_missing_status_reader_is_unavailable():
    client, heard = _status_client({"robot-01": object()})
    with client:
        result = client.get("/v1/robots/robot-01/status")
    assert result.status_code == 503
    assert result.json() == {"detail": "Status adapter unavailable"}
    assert heard == []


def test_unsupported_aux_reader_remains_diagnostic():
    client, heard = _status_client({"robot-01": object()})
    with client:
        result = client.get("/v1/robots/robot-01/aux")
    assert result.status_code == 200
    assert result.json()["available"] is False
    assert heard == []


def test_status_preserves_incomplete_source_metadata():
    packet = {"robot_id": "robot-01", "armed": False, "imu": {"valid": False}}

    async def status():
        return packet

    client, _ = _status_client({"robot-01": SimpleNamespace(status=status)})
    with client:
        result = client.get("/v1/robots/robot-01/status")
    assert result.status_code == 200
    assert result.json() == packet
