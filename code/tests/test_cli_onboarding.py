"""First-minute diagnostics remain read-only and give actionable failures."""

import json
import sqlite3
import sys
from types import SimpleNamespace

import pytest
from desk_robot import cli


def _settings(**overrides):
    return SimpleNamespace(**{
        "mode": "hardware",
        "coordinator_token_env": "OPERATOR",
        "tools_token_env": "TOOLS",
        "robots": [SimpleNamespace(id="pet", motion_enabled=False, calibration=None)],
        "room_station_enabled": False,
        "room_station_port": None,
        **overrides,
    })


def _invoke(monkeypatch, settings, action):
    monkeypatch.setattr(cli, "load_settings", lambda _: settings)
    monkeypatch.setattr(cli, "load_env", lambda _: None)
    monkeypatch.setattr(sys, "argv", ["desk-robot", action])
    cli.main()


def test_doctor_missing_serial_has_next_action(monkeypatch, capsys, tmp_path):
    port = "/dev/ttyACM999999999"
    settings = _settings(
        room_station_enabled=True, room_station_port=port, memory_dir=tmp_path / "memory",
    )
    _invoke(monkeypatch, settings, "doctor")
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert report["room_station"]["status"] == "device_unavailable"
    assert "room_station_port" in report["room_station"]["next_action"]
    assert report["physical_test_status"] == "not run"
    assert not output.err
    assert list(tmp_path.iterdir()) == []


def test_doctor_disabled_station_does_not_probe(monkeypatch, capsys):
    def unexpected_probe(port):
        pytest.fail("Disabled room station must not be probed")

    monkeypatch.setattr(cli, "require_local_serial_device", unexpected_probe)
    _invoke(monkeypatch, _settings(), "doctor")
    assert json.loads(capsys.readouterr().out)["room_station"]["status"] == "disabled"


def test_doctor_present_device_does_not_claim_hardware_verification(monkeypatch, capsys):
    monkeypatch.setattr(cli, "require_local_serial_device", lambda port: None)
    _invoke(monkeypatch, _settings(
        room_station_enabled=True, room_station_port="/dev/ttyACM0",
    ), "doctor")
    report = json.loads(capsys.readouterr().out)
    assert report["room_station"]["status"] == "device_present_not_verified"
    assert report["physical_test_status"] == "not run"


def test_demo_sqlite_startup_error_is_actionable(monkeypatch, capsys, tmp_path):
    async def unavailable_memory(settings):
        sqlite3.connect(tmp_path / "missing" / "pet.sqlite3")

    monkeypatch.setattr(cli.Runtime, "create", unavailable_memory)
    with pytest.raises(SystemExit) as stopped:
        _invoke(monkeypatch, _settings(mode="simulation"), "demo")
    assert stopped.value.code == 1
    output = capsys.readouterr()
    assert not output.out
    assert "memory_dir" in output.err
    assert "Traceback" not in output.err
    assert str(tmp_path) not in output.err
