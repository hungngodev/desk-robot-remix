"""Head provisioning follows the selected fleet even from another directory."""

import importlib.util
import json
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
    (board / "config.json").write_text(json.dumps({"builds": [{"sdkconfig_append": []}]}))
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
    assert target.stat().st_mode & 0o777 == 0o600
    output = capsys.readouterr()
    assert expected not in output.out + output.err
