"""Malformed local fleet configuration must stop the launcher cleanly."""

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
