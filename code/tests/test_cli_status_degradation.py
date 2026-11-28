"""The status CLI prints structured degradation and preserves failure exit codes."""
import json
import sys
from types import SimpleNamespace

import httpx
import pytest
from desk_robot import cli


@pytest.mark.parametrize(("code", "state", "robot_id", "action", "prints_json", "exit_code"), [
    (200, "reported", "pet", "status", True, 0),
    (200, "unverified", "pet", "status", True, 2),
    (200, "degraded", "pet", "status", True, 1),
    (503, "degraded", "pet", "status", True, 1),
    (503, "degraded", "foreign", "status", False, 1),
    (503, "reported", "pet", "status", False, 1),
    (403, "degraded", "pet", "status", False, 1),
    (503, "degraded", "pet", "stop", False, 1),
])
def test_status_cli_degraded_json_and_exit(
    code, state, robot_id, action, prints_json, exit_code, monkeypatch, capsys,
):
    packet = {"robot_id": robot_id, "health": {
        "head": "responded", "body": "serial_timeout", "state": state,
        "room_station": "unavailable", "physical_acceptance_pass": False,
    }}
    requests = []

    def respond(request):
        requests.append((request.method, request.url.path))
        return httpx.Response(code, json=packet)

    original = httpx.AsyncClient
    monkeypatch.setattr(cli.httpx, "AsyncClient", lambda **kwargs: original(
        transport=httpx.MockTransport(respond), **kwargs,
    ))
    monkeypatch.setenv("OPERATOR", "a" * 40)
    monkeypatch.setattr(cli, "load_settings", lambda _: SimpleNamespace(
        coordinator_token_env="OPERATOR", mode="hardware",
    ))
    monkeypatch.setattr(cli, "load_env", lambda _: None)
    monkeypatch.setattr(sys, "argv", ["desk-robot", action, "pet"])
    if exit_code:
        with pytest.raises(SystemExit) as stopped:
            cli.main()
        assert stopped.value.code == exit_code
    else:
        cli.main()
    output = capsys.readouterr()
    if prints_json:
        assert json.loads(output.out) == packet
    else:
        assert output.out == ""
        assert output.err
    assert requests == [("GET" if action == "status" else "POST", f"/v1/robots/pet/{action}")]


@pytest.mark.parametrize(("error", "expected"), [
    (httpx.InvalidURL("private-marker"), "Invalid coordinator URL"),
    (httpx.ReadTimeout(""), "Coordinator request timed out; completion unconfirmed."),
    (httpx.ConnectError("private-marker"),
     "Coordinator HTTP request failed; completion unconfirmed."),
    (httpx.HTTPStatusError("private-marker",
                           request=httpx.Request("POST", "http://localhost"),
                           response=httpx.Response(503)),
     "Coordinator returned HTTP 503; completion unconfirmed."),
])
def test_http_failure_is_sanitized_and_not_retried(monkeypatch, capsys, error, expected):
    calls = []

    async def request(args, settings):
        calls.append(args.action)
        raise error

    monkeypatch.setattr(cli, "request", request)
    monkeypatch.setattr(cli, "load_settings", lambda _: SimpleNamespace())
    monkeypatch.setattr(cli, "load_env", lambda _: None)
    monkeypatch.setattr(sys, "argv", ["desk-robot", "stop", "pet"])
    with pytest.raises(SystemExit) as stopped:
        cli.main()
    assert stopped.value.code == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err.strip() == expected
    assert "private-marker" not in output.err
    assert calls == ["stop"]


def test_enabled_room_station_no_receipt_reports_unverified_and_exits_2(
    settings, tokens, monkeypatch, capsys,
):
    from desk_robot.api import create_app
    from fastapi.testclient import TestClient

    async def noop():
        pass

    async def status():
        return {"robot_id": "robot-01", "armed": False}

    settings.mode = "hardware"
    settings.room_station_enabled = True
    runtime = SimpleNamespace(
        start=noop,
        close=noop,
        _closed=False,
        coordinator=SimpleNamespace(
            robot=lambda _rid: None,
            heads={"robot-01": SimpleNamespace(status=status)},
            stop_confirmations=SimpleNamespace(status=lambda _rid: None),
        ),
        room_feed=SimpleNamespace(last_error=None),
    )
    monkeypatch.setattr(cli, "load_settings", lambda _: settings)
    monkeypatch.setattr(cli, "load_env", lambda _: None)
    monkeypatch.setattr(sys, "argv", ["desk-robot", "status", "robot-01"])

    app = create_app(settings, runtime=runtime)
    test_client = TestClient(app)
    with test_client:
        def _forward(req):
            resp = test_client.request(
                req.method,
                req.url.raw_path.decode(),
                headers=req.headers,
                content=req.content,
            )
            return httpx.Response(resp.status_code, content=resp.content, headers=resp.headers)

        original = httpx.AsyncClient
        monkeypatch.setattr(
            cli.httpx,
            "AsyncClient",
            lambda **kwargs: original(transport=httpx.MockTransport(_forward), **kwargs),
        )
        with pytest.raises(SystemExit) as stopped:
            cli.main()
    assert stopped.value.code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["health"]["room_station"] == "unverified"
    assert payload["health"]["state"] == "unverified"
    assert payload["health"]["physical_acceptance_pass"] is False
