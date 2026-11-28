"""Verify the host Python contract and exercise the CI dependency fence."""

import json
import os
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml


@pytest.mark.parametrize(
    ("job", "step_name"),
    [
        ("mac-fast", "Verify imports with locked runtime dependencies only"),
        ("mac-fast", "Install locked Mac test dependencies"),
        ("python-and-head-host", "Install Python and locked dependencies"),
    ],
)
def test_host_ci_python_matches_toolchain_lock(job, step_name):
    code = Path(__file__).resolve().parents[1]
    reference = json.loads((code / "toolchain-lock.json").read_text())["python"]
    project = tomllib.loads((code / "pyproject.toml").read_text())
    assert project["project"]["requires-python"] == f">={reference}"
    workflow = yaml.safe_load(
        (code.parent / ".github/workflows/host-verification.yml").read_text()
    )
    step = next(
        step for step in workflow["jobs"][job]["steps"] if step.get("name") == step_name
    )
    lines = step["run"].splitlines()
    assert [line for line in lines if line.startswith("uv python install ")] == [
        f"uv python install {reference}"
    ]
    sync = [line.split() for line in lines if line.startswith("uv sync ")]
    assert len(sync) == 1
    assert sync[0][sync[0].index("--python") + 1] == reference
    assert "--locked" in sync[0]


@pytest.mark.parametrize(
    "fault",
    ["none", "numpy-drift", "missing-opencv", "bad-metadata", "extra-package", "wrong-opencv"],
)
def test_opencv_install_preserves_locked_environment(tmp_path, fault):
    code = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load(
        (code.parent / ".github/workflows/host-verification.yml").read_text()
    )
    step = next(
        step for step in workflow["jobs"]["python-and-head-host"]["steps"]
        if step.get("name") == "Install pinned headless OpenCV for dock geometry tests"
    )
    fake_uv = tmp_path / "uv"
    fake_uv.write_text(
        """#!/bin/bash
set -eu
case "$1 $2" in
  'pip freeze')
    if [ -f installed ]; then
      if [ "$FAULT" = numpy-drift ]; then echo 'numpy==9.9'; else echo 'numpy==2.4.6'; fi
      case "$FAULT" in
        missing-opencv) ;;
        wrong-opencv) echo 'opencv-python-headless==4.0.0' ;;
        *) echo 'opencv-python-headless==4.13.0.92' ;;
      esac
      if [ "$FAULT" = extra-package ]; then echo 'unexpected-package==1.0'; fi
    else
      echo 'numpy==2.4.6'
    fi
    echo 'pytest==9.2.0'
    ;;
  'pip install')
    shift 2
    [ "$*" = '--python .venv/bin/python --no-deps --only-binary :all: --require-hashes -r requirements-ci-opencv.txt' ]
    touch installed
    ;;
  'pip check')
    [ "$FAULT" != bad-metadata ]
    ;;
  *) exit 99 ;;
esac
"""
    )
    fake_uv.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "FAULT": fault}
    result = subprocess.run(
        ["bash", "-c", step["run"]], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=30,
    )
    assert (result.returncode == 0) == (fault == "none"), result.stdout + result.stderr
