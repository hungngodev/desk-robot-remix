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
