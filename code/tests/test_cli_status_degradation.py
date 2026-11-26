"""The status CLI prints structured degradation and preserves failure exit codes."""
import json
import sys
from types import SimpleNamespace

import httpx
import pytest
from desk_robot import cli


@pytest.mark.parametrize(("code", "state", "robot_id", "action", "prints_json", "exit_code"), [
    (200, "reported", "pet", "status", True, 0),
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
