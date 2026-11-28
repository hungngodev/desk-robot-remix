"""Hardware HTTP status must not negotiate motion with legacy wire schemas."""

import json
from types import SimpleNamespace

import httpx
import pytest
from desk_robot.transport import HeadError, HttpHead


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", [None, 1, 3, True, 2.0, "2"])
async def test_hardware_status_rejects_unsupported_wire_protocol(monkeypatch, protocol):
    monkeypatch.setattr("desk_robot.transport.secret", lambda _: "fixture-token")
    config = SimpleNamespace(
        id="robot-01", head_url="http://robot.invalid", token_env="HEAD_TOKEN",
    )
    sent = []
    body = {
        "robot_id": "robot-01", "armed": False,
        "ranges": {"present_mask": 31, "valid_mask": 31, "mm": [50] * 4 + [500]},
        "safety": {"required": True, "ready": True, "fault": "none"},
    }
    if protocol is not None:
        body["protocol"] = protocol

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json=body)
        command = json.loads(request.content)["command"]
        sent.append(command)
        return httpx.Response(200, json={
            "ok": True, "robot_id": "robot-01", "reply": f"OK {command}",
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(config, client, require_body_protocol=True)
        with pytest.raises(HeadError, match="protocol not verified"):
            await head.command("arm")
        with pytest.raises(HeadError, match="Unsupported WROOM status protocol"):
            await head.status()
        with pytest.raises(HeadError, match="require acknowledged HALT"):
            await head.command("arm")
        assert sent == []
        await head.command("halt")
        assert sent == ["halt"]
        with pytest.raises(HeadError, match="protocol not verified"):
            await head.command("arm")
        body["protocol"] = 2
        assert await head.status() == body
        await head.command("arm")
        assert sent == ["halt", "arm"]
        del body["protocol"]
        with pytest.raises(HeadError, match="Unsupported WROOM status protocol"):
            await head.status()
        with pytest.raises(HeadError, match="require acknowledged HALT"):
            await head.command("keepalive")
        await head.command("halt")
        assert sent == ["halt", "arm", "halt"]


@pytest.mark.asyncio
async def test_legacy_diagnostic_adapter_can_read_unversioned_status(monkeypatch):
    monkeypatch.setattr("desk_robot.transport.secret", lambda _: "fixture-token")
    config = SimpleNamespace(
        id="robot-01", head_url="http://robot.invalid", token_env="HEAD_TOKEN",
    )
    body = {"robot_id": "robot-01", "armed": False}
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=body))
    async with httpx.AsyncClient(transport=transport) as client:
        head = HttpHead(config, client)
        assert await head.status() == body
