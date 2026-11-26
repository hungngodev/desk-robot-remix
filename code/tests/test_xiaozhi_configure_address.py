"""Xiaozhi head provisioning accepts only usable IPv4 host addresses."""

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def configure():
    spec = importlib.util.spec_from_file_location(
        "xiaozhi_configure_address", ROOT / "laptop/server/configure.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("address", ["224.0.0.1", "240.0.0.1", "255.255.255.255", "0.1.2.3"])
def test_non_host_address_rejected_before_config_access(
    configure, monkeypatch, tmp_path, capsys, address,
):
    monkeypatch.setattr(configure, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["configure.py", "--server-ip", address])
    with pytest.raises(SystemExit) as error:
        configure.main()
    assert error.value.code == 2
    assert "reachable LAN IPv4 address" in capsys.readouterr().err
    assert not list(tmp_path.iterdir())


def test_lan_address_keeps_authenticated_head_configuration(configure, monkeypatch, tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config/xiaozhi.local.example.yaml").write_text(
        "server:\n  auth:\n    enabled: true\n    allowed_devices: []\n"
    )
    target = tmp_path / "laptop/server/build/xiaozhi/main/xiaozhi-server/data/.config.yaml"
    target.parent.parent.mkdir(parents=True)
    monkeypatch.setattr(configure, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["configure.py", "--server-ip", "192.168.1.20"])
    configure.main()
    server = yaml.safe_load(target.read_text())["server"]
    assert server["websocket"] == "ws://192.168.1.20:8000/xiaozhi/v1/"
    assert server["auth"] == {"enabled": True, "allowed_devices": []}
    assert len(server["auth_key"]) >= 32
    assert target.stat().st_mode & 0o777 == 0o600
