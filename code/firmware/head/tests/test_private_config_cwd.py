"""Head provisioning follows the selected fleet even from another directory."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "private_config_cwd", Path(__file__).resolve().parents[1] / "private_config.py"
)
private = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(private)


@pytest.mark.parametrize("explicit", [False, True])
def test_private_config_credentials_follow_fleet(tmp_path, monkeypatch, capsys, explicit):
    root = tmp_path / "repo"
    canonical = root / "config"
    canonical.mkdir(parents=True)
    fleet = tmp_path / "fleet"
    fleet.mkdir()
    (fleet / "local.toml").write_text(
        '[[robots]]\nid="robot-01"\ntoken_env="DRX_TEST_HEAD_TOKEN"\n'
    )
    expected = "x" * 40
    for path, token in [
        (canonical / "local.env", "y" * 40),
        (fleet / "local.env", "z" * 40 if explicit else expected),
        (fleet / "override.env", expected),
    ]:
        path.write_text(f"DRX_TEST_HEAD_TOKEN={token}\n")
        path.chmod(0o600)
    board = root / "firmware/head/build/xiaozhi-sense/main/boards/desk-robot/desk-robot-sense-s3"
    board.mkdir(parents=True)
    stale = [
        "CONFIG_DESK_ROBOT_AEC_DELAY_MS=0",
        "CONFIG_DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED=y",
        "CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED=y",
    ]
    (board / "config.json").write_text(json.dumps({"builds": [{"sdkconfig_append": stale}]}))
    working = tmp_path / "unrelated"
    working.mkdir()
    monkeypatch.chdir(working)
    monkeypatch.setattr(private, "ROOT", root)
    monkeypatch.delenv("DRX_TEST_HEAD_TOKEN", raising=False)
    args = ["private_config.py", "--board", "sense", "--robot", "robot-01",
            "--server-ip", "192.168.1.15", "--config", "../fleet/local.toml"]
    if explicit:
        args.extend(["--secrets", "../fleet/override.env"])
    monkeypatch.setattr(sys, "argv", args)
    private.main()
    target = board / "config.private.json"
    settings = json.loads(target.read_text())["builds"][0]["sdkconfig_append"]
    assert f'CONFIG_DESK_ROBOT_TOKEN="{expected}"' in settings
    for setting in (
        "CONFIG_DESK_ROBOT_AEC_DELAY_MS=90",
        "CONFIG_DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED=n",
        "CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED=n",
    ):
        key = setting.split("=", 1)[0] + "="
        assert [entry for entry in settings if entry.startswith(key)] == [setting]
    assert target.stat().st_mode & 0o777 == 0o600
    output = capsys.readouterr()
    assert expected not in output.out + output.err


def test_private_config_import_preserves_process_state(tmp_path):
    script = """
import importlib.util
import os
import sys

original_path = sys.path[:]
original_env = dict(os.environ)
for name in ("private_config_first", "private_config_second"):
    spec = importlib.util.spec_from_file_location(name, sys.argv[1])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert callable(module.read_private_env)
    assert sys.path == original_path, "private configuration import changed sys.path"
    assert dict(os.environ) == original_env, "private configuration import changed environment"
"""
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-c", script, str(SPEC.origin)],
        cwd=tmp_path, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
