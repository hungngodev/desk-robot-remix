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
        room_station_enabled=False,
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


@pytest.mark.parametrize(
    ("enabled", "port", "available", "expected"),
    [
        (False, None, False, "disabled"),
        (True, None, False, "device_unavailable"),
        (True, "/dev/tty.test", False, "device_unavailable"),
        (True, "/dev/tty.test", True, "device_present_not_verified"),
    ],
)
def test_doctor_reports_degraded_optional_subsystems_without_hardware(
    enabled, port, available, expected, monkeypatch, capsys,
):
    settings = SimpleNamespace(
        mode="hardware", coordinator_token_env="DRX_TEST_OPERATOR",
        tools_token_env="DRX_TEST_TOOLS", robots=[], room_station_enabled=enabled,
        room_station_port=port,
    )
    probes = []

    def check_device(value):
        probes.append(value)
        if not available:
            raise ValueError("device unavailable")

    monkeypatch.setattr(cli, "load_settings", lambda _: settings)
    monkeypatch.setattr(cli, "load_env", lambda _: None)
    monkeypatch.setattr(cli.shutil, "which", lambda _: None)
    monkeypatch.setattr(cli, "require_local_serial_device", check_device)
    monkeypatch.delenv("DRX_TEST_OPERATOR", raising=False)
    monkeypatch.delenv("DRX_TEST_TOOLS", raising=False)
    monkeypatch.setattr(sys, "argv", ["desk-robot", "doctor"])
    cli.main()
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert not captured.err
    assert report["room_station"]["status"] == expected
    assert ("next_action" in report["room_station"]) == (expected == "device_unavailable")
    assert probes == ([port] if enabled and port else [])
    assert report["ollama_installed"] is False
    assert report["ffmpeg_installed"] is False
    assert report["credentials_present"] is False
    assert "credentials_next_action" in report
    assert report["physical_test_status"] == "not run"
    assert "live_media" not in report
