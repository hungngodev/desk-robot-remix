"""Malformed local fleet configuration must stop the launcher cleanly."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("content", [None, b'robots = [', b'\xff'])
def test_invalid_fleet_file_reports_cli_error(tmp_path, content):
    config = tmp_path / "fleet.toml"
    if content is not None:
        config.write_bytes(content)
    result = subprocess.run(
        [sys.executable, str(ROOT / "laptop/server/run_server.py"), "--config", str(config)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 2
    assert "Cannot read fleet configuration" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("explicit", [False, True])
def test_launcher_credentials_follow_selected_config_from_other_cwd(tmp_path, explicit):
    config_dir = tmp_path / "fleet"
    config_dir.mkdir()
    config = config_dir / "local.toml"
    config.write_text('[[robots]]\nid = "robot-01"\ndevice_id = "head-01"\nvoice = "af_heart"\n')
    working = tmp_path / "unrelated"
    working.mkdir()
    # A malformed selected file must fail before any installed server is used.
    credentials = config_dir / ("custom.env" if explicit else "local.env")
    credentials.write_text("EXAMPLE=one\nEXAMPLE=two\n")
    credentials.chmod(0o600)
    args = [sys.executable, str(ROOT / "laptop/server/run_server.py"),
            "--config", "../fleet/local.toml"]
    if explicit:
        args.extend(["--secrets", "../fleet/custom.env"])
    result = subprocess.run(
        args, cwd=working, capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode == 2
    assert "Credential file contains a malformed or duplicate entry" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.fixture
def launcher(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "drx1106_launcher", ROOT / "laptop/server/run_server.py",
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.syspath_prepend(str(ROOT / "laptop/src"))
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("device_id", [False, 0, None, [], {}])
def test_launcher_rejects_nonstring_unmapped_device(launcher, device_id):
    robots = [
        {"id": "robot-01", "device_id": "head-01", "voice": "af_heart"},
        {"id": "robot-02", "device_id": device_id, "voice": "af_bella"},
    ]
    with pytest.raises(ValueError, match="Provisioned robot needs an ID, device and Kokoro voice"):
        launcher.fleet_device_and_voice_maps(robots)


@pytest.mark.parametrize("unmapped", [{}, {"device_id": ""}])
def test_launcher_accepts_unprovisioned_sibling(launcher, unmapped):
    robots = [
        {"id": "robot-01", "device_id": "head-01", "voice": "af_heart"},
        {"id": "robot-02", "voice": "af_bella", **unmapped},
    ]
    assert launcher.fleet_device_and_voice_maps(robots) == (
        {"robot-01": "head-01"}, {"robot-01": "af_heart"},
    )
