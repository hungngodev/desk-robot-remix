"""Exercise the public doctor entry point after separating CLI dispatch."""
import json
import sys
from types import SimpleNamespace

import pytest
from desk_robot import cli


@pytest.mark.parametrize(
    ("flags", "expected_look"),
    [([], None), (["--live"], False), (["--look"], True), (["--live", "--look"], True)],
)
def test_doctor_only_requests_live_media_when_requested(
    flags, expected_look, monkeypatch, capsys,
):
    settings = SimpleNamespace(
        mode="hardware", coordinator_token_env="OPERATOR", tools_token_env="TOOLS",
        robots=[SimpleNamespace(id="pet", motion_enabled=False, calibration=None)],
    )
    calls = []

    async def inspect(config, robot_id, *, look, base_url):
        assert config is settings
        calls.append((robot_id, look, base_url))
        return {"motor_armed_or_charging_verified": False}

    monkeypatch.setattr(cli, "load_settings", lambda _: settings)
    monkeypatch.setattr(cli, "load_env", lambda _: None)
    monkeypatch.setattr(cli, "inspect_live_media", inspect)
    monkeypatch.setattr(sys, "argv", [
        "desk-robot", "--url", "http://127.0.0.1:9876", "doctor", *flags,
    ])
    cli.main()
    report = json.loads(capsys.readouterr().out)
    assert report["physical_test_status"] == "not run"
    if expected_look is None:
        assert calls == []
        assert "live_media" not in report
    else:
        assert calls == [("pet", expected_look, "http://127.0.0.1:9876")]
        assert report["live_media"] == {"motor_armed_or_charging_verified": False}
