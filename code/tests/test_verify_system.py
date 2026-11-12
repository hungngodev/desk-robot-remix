"""Verification runner must never turn failed CI into a fake accepted robot."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "desk_robot_verify", ROOT / "code/scripts/verify_system.py"
)
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)


def test_every_real_host_and_firmware_stage_is_in_canonical_runner(tmp_path):
    jobs = verify.steps("all", tmp_path)
    names = [name for name, *_ in jobs]
    assert names == [
        "python-tests", "python-lint", "body-cmake", "body-compile",
        "body-ctest", "wroom-esp32_full", "wroom-esp32_stepper",
        "wroom-esp32dev", "sense-build",
    ]
    assert verify.steps("body", tmp_path)[-1][0] == "body-ctest"
    with pytest.raises(ValueError):
        verify.steps("physical-accepted-by-a-badge", tmp_path)


def test_runner_returns_real_failures_and_does_not_retry_motion(monkeypatch, tmp_path):
    calls = []

    def failed(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=7, stdout="compiler failed",
                               stderr="test assertion failed")

    monkeypatch.setattr(verify.subprocess, "run", failed)
    result = verify.run("body-ctest", ["ctest", "--test-dir", str(tmp_path)],
                        tmp_path, 1)
    assert result["pass"] is False
    assert result["exit_code"] == 7
    assert "compiler failed" in result["output_tail"]
    assert len(calls) == 1


def test_missing_tool_returns_incomplete_not_success(monkeypatch, tmp_path):
    def missing(*args, **kwargs):
        raise FileNotFoundError("pio not installed")

    monkeypatch.setattr(verify.subprocess, "run", missing)
    result = verify.run("wroom-full", ["pio", "run"], tmp_path, 1)
    assert result["pass"] is False
    assert result["exit_code"] is None
    assert "FileNotFoundError" in result["error"]
