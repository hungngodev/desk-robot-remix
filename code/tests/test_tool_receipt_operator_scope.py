"""Only a signed current Xiaozhi tool request may become spoken context."""

import hashlib
import hmac
import json
import time
from itertools import combinations
from types import SimpleNamespace

import pytest
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
        # Signed Xiaozhi generation is independent of the camera/Mac epoch.
        # A valid HMAC without this authenticated live source must fail closed.
        _voice_turn_generations={robot_id: 7},
        voice_events=SimpleNamespace(monitor_ready=True, _event_generation=11),
        pet=SimpleNamespace(voice_monitor_ready=True),
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
        # Reject malformed numeric headers before int conversion, without
        # consuming the valid receipt or adding a spoken fact.
        for header in (
            "X-Desk-Robot-Tool-Receipt-At-Us",
            "X-Desk-Robot-Tool-Receipt-Generation",
        ):
            for digits in ("9" * 20, "9" * 5000):
                malformed = {**tool, **signed, header: digits}
                assert client.get(url, headers=malformed).status_code == 409
                assert not hub.tool_history[robot_id]

        legitimate = client.get(url, headers={**tool, **signed})
        assert legitimate.status_code == 200
        assert len(hub.tool_history[robot_id]) == 1
        assert hub.tool_history[robot_id][0][0] == "robot_status"

        # HMAC authenticity alone cannot grant a new or old speaking turn.
        # The source monitor currently owns generation 7, not generation 6.
        mismatched_generation = _signed_headers(
            speech_token,
            robot_id=robot_id,
            device_id="mac-01",
            generation=6,
            method="GET",
            path=url,
            receipt_id="6" * 32,
        )
        assert client.get(
            url, headers={**tool, **mismatched_generation},
        ).status_code == 409
        assert len(hub.tool_history[robot_id]) == 1

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

        # The explicit Xiaozhi context tool uses the same signed provenance
        # contract as status, unlike ordinary native context polling.
        situation_url = f"/v1/pet/{robot_id}/interaction-context"
        context_signed = _signed_headers(
            speech_token,
            robot_id=robot_id,
            device_id="mac-01",
            generation=7,
            method="GET",
            path=situation_url,
            receipt_id="7" * 32,
        )
        context_wrong_generation = _signed_headers(
            speech_token,
            robot_id=robot_id,
            device_id="mac-01",
            generation=6,
            method="GET",
            path=situation_url,
            receipt_id="8" * 32,
        )
        assert client.get(situation_url, headers=tool).status_code == 200
        assert client.get(
            situation_url, headers={**tool, **context_wrong_generation},
        ).status_code == 409
        assert client.get(
            situation_url, headers={
                **tool, **context_signed,
                "X-Desk-Robot-Tool-Receipt-Signature": "0" * 64,
            },
        ).status_code == 409
        accepted_context = client.get(
            situation_url, headers={**tool, **context_signed},
        )
        assert accepted_context.status_code == 200
        assert accepted_context.json()["robot_id"] == robot_id
        assert accepted_context.json()["motor_authorized"] is False
        assert client.get(
            situation_url, headers={**tool, **context_signed},
        ).status_code == 409
        assert len(hub.tool_history[robot_id]) == 1


@pytest.mark.parametrize("left,right", list(combinations(range(5), 2)))
def test_api_startup_rejects_reused_credential_values(settings, monkeypatch, left, right):
    names = [
        settings.coordinator_token_env,
        settings.tools_token_env,
        settings.speech_bridge_token_env,
        *(r.token_env for r in settings.robots),
    ]
    values = [chr(97 + index) * 40 for index in range(len(names))]
    for name, value in zip(names, values, strict=True):
        monkeypatch.setenv(name, value)
    # Match secret() normalization, not just raw environment strings.
    monkeypatch.setenv(names[right], " " + values[left] + " ")
    started = []

    async def start():
        started.append(True)

    async def close():
        pass

    runtime = SimpleNamespace(start=start, close=close)
    with pytest.raises(ValueError, match="different|distinct") as exc:
        with TestClient(create_app(settings, runtime=runtime)):
            pytest.fail("API served requests despite credential reuse")
    assert not started
    assert values[left] not in str(exc.value)


def test_distinct_head_and_tool_tokens_cannot_call_operator_routes(settings, monkeypatch):
    names = [
        settings.coordinator_token_env,
        settings.tools_token_env,
        settings.speech_bridge_token_env,
        *(r.token_env for r in settings.robots),
    ]
    values = [chr(97 + index) * 40 for index in range(len(names))]
    for name, value in zip(names, values, strict=True):
        monkeypatch.setenv(name, value)

    async def noop():
        pass

    # No actuator or memory handler exists on this runtime: any accidental
    # execution of an operator handler will fail this regression.
    runtime = SimpleNamespace(start=noop, close=noop)
    robot_id = settings.robots[0].id
    with TestClient(create_app(settings, runtime=runtime)) as client:
        for index, token in enumerate(values[1:], start=1):
            headers = {"Authorization": "Bearer " + token}
            expected = 403 if index == 1 else 401
            assert client.post(
                f"/v1/robots/{robot_id}/enable", headers=headers,
            ).status_code == expected
            assert client.post(
                f"/v1/robots/{robot_id}/move", headers=headers,
                json={"command": "drive 20 20"},
            ).status_code == expected
            assert client.delete(
                f"/v1/pet/{robot_id}/memories/example", headers=headers,
            ).status_code == expected
            assert client.delete(
                f"/v1/pet/{robot_id}/core-memory/example", headers=headers,
            ).status_code == expected
