"""Exercise the actual speech bridge authentication middleware."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

TOKEN = "s" * 40


@pytest.fixture
def bridge(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "laptop/server/overlay/desk_robot_bridge.py"
    spec = importlib.util.spec_from_file_location("test_bridge_auth_headers", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    monkeypatch.setenv("DESK_ROBOT_SPEECH_TOKEN", TOKEN)
    monkeypatch.setenv("DESK_ROBOT_DEVICE_MAP", json.dumps({"robot-01": "mac-01"}))
    return module


@pytest.mark.parametrize(
    "headers,expected",
    [
        ([], 401),
        ([("Authorization", "Bearer " + TOKEN)], 200),
        ([("Authorization", "bEaReR " + TOKEN)], 200),
        ([("Authorization", "Basic " + TOKEN)], 401),
        ([("Authorization", "Bearer  " + TOKEN)], 401),
        ([("Authorization", "Bearer " + TOKEN + " extra")], 401),
        ([("Authorization", "Bearer café")], 401),
        ([("Authorization", "Bearer " + "x" * 40)], 401),
        ([("Authorization", "Bearer " + TOKEN), ("Authorization", "Bearer wrong")], 401),
        ([("Authorization", "Bearer " + TOKEN), ("Authorization", "Bearer " + TOKEN)], 401),
    ],
)
async def test_bridge_authorization_headers(bridge, headers, expected):
    async with TestClient(TestServer(bridge.create_app())) as client:
        response = await client.get("/events", headers=headers)
        assert response.status == expected
        assert TOKEN not in await response.text()


@pytest.mark.parametrize("token", ["s" * 24 + "é", "s" * 24 + " ", "s" * 24 + ":"])
def test_bridge_rejects_malformed_configured_token(bridge, monkeypatch, token):
    monkeypatch.setenv("DESK_ROBOT_SPEECH_TOKEN", token)
    with pytest.raises(ValueError, match="DESK_ROBOT_SPEECH_TOKEN"):
        bridge.create_app()
