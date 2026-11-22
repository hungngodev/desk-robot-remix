"""Only a signed current Xiaozhi tool request may become spoken context."""

import hashlib
import hmac
import json
import time
from types import SimpleNamespace

from desk_robot.api import create_app
from desk_robot.multimodal import CameraFrameHub
from fastapi.testclient import TestClient


def _signed_headers(
    token,
    *,
    robot_id,
    device_id,
    generation,
    method,
    path,
    receipt_id,
    issued_us=None,
):
    issued_us = time.time_ns() // 1000 if issued_us is None else issued_us
    message = json.dumps(
        [
            1,
            robot_id,
            device_id,
            generation,
            method.upper(),
            path,
            issued_us,
            receipt_id,
        ],
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return {
        "X-Desk-Robot-Tool-Receipt": "1",
        "X-Desk-Robot-Tool-Receipt-Id": receipt_id,
        "X-Desk-Robot-Tool-Receipt-At-Us": str(issued_us),
        "X-Desk-Robot-Tool-Receipt-Device": device_id,
        "X-Desk-Robot-Tool-Receipt-Generation": str(generation),
        "X-Desk-Robot-Tool-Receipt-Signature": hmac.new(
            token.encode("utf-8"), message, hashlib.sha256
        ).hexdigest(),
    }


def test_tool_bearer_alone_cannot_promote_dashboard_read_to_voice_tool(
    settings, tokens, monkeypatch,
):
    settings.mode = "hardware"
    robot_id = settings.robots[0].id
    settings.robots[0].device_id = "mac-01"
    speech_token = "s" * 40
    monkeypatch.setenv("DESK_ROBOT_SPEECH_TOKEN", speech_token)
    hub = CameraFrameHub([robot.id for robot in settings.robots])
    visual = SimpleNamespace(
        _turn_epoch={robot.id: 3 for robot in settings.robots},
        hub=hub,
    )

    class Head:
        async def status(self):
            return {
                "robot_id": robot_id,
                "backend": "reported_head",
                "armed": False,
                "safety": {"fault": "none"},
            }

    async def noop():
        pass

    runtime = SimpleNamespace(
        coordinator=SimpleNamespace(
            robot=lambda rid: settings.robot(rid),
            heads={robot_id: Head()},
        ),
        multimodal=visual,
        start=noop,
        close=noop,
    )
    app = create_app(settings, runtime=runtime)
    operator = {
        "Authorization": "Bearer " + tokens["DESK_ROBOT_API_TOKEN"],
    }
    tool = {
        "Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"],
    }
    url = f"/v1/robots/{robot_id}/status"
    with TestClient(app) as client:
        dashboard = client.get(url, headers=operator)
        assert dashboard.status_code == 200
        assert dashboard.json()["robot_id"] == robot_id
        assert not hub.tool_history[robot_id]

        forged_operator = client.get(
            url, headers={**operator, "X-Desk-Robot-Tool-Receipt": "1"},
        )
        assert forged_operator.status_code == 409
        assert not hub.tool_history[robot_id]

        unsigned_tool = client.get(
            url, headers={**tool, "X-Desk-Robot-Tool-Receipt": "1"},
        )
        assert unsigned_tool.status_code == 409
        assert not hub.tool_history[robot_id]

        signed = _signed_headers(
            speech_token,
            robot_id=robot_id,
            device_id="mac-01",
            generation=7,
            method="GET",
            path=url,
            receipt_id="1" * 32,
        )
        legitimate = client.get(url, headers={**tool, **signed})
        assert legitimate.status_code == 200
        assert len(hub.tool_history[robot_id]) == 1
        assert hub.tool_history[robot_id][0][0] == "robot_status"

        replay = client.get(url, headers={**tool, **signed})
        assert replay.status_code == 409
        assert len(hub.tool_history[robot_id]) == 1

        wrong_path = _signed_headers(
            speech_token,
            robot_id=robot_id,
            device_id="mac-01",
            generation=7,
            method="GET",
            path=f"/v1/robots/{robot_id}/aux",
            receipt_id="2" * 32,
        )
        assert client.get(url, headers={**tool, **wrong_path}).status_code == 409

        wrong_device = _signed_headers(
            speech_token,
            robot_id=robot_id,
            device_id="other-head",
            generation=7,
            method="GET",
            path=url,
            receipt_id="3" * 32,
        )
        assert client.get(url, headers={**tool, **wrong_device}).status_code == 409

        expired = _signed_headers(
            speech_token,
            robot_id=robot_id,
            device_id="mac-01",
            generation=7,
            method="GET",
            path=url,
            receipt_id="4" * 32,
            issued_us=time.time_ns() // 1000 - 6_000_000,
        )
        assert client.get(url, headers={**tool, **expired}).status_code == 409

        bad_signature = {
            **_signed_headers(
                speech_token,
                robot_id=robot_id,
                device_id="mac-01",
                generation=7,
                method="GET",
                path=url,
                receipt_id="5" * 32,
            ),
            "X-Desk-Robot-Tool-Receipt-Signature": "0" * 64,
        }
        assert client.get(url, headers={**tool, **bad_signature}).status_code == 409
        assert len(hub.tool_history[robot_id]) == 1
