"""Exercise the CI dependency fence with an adversarial installer."""

import os
import subprocess
from pathlib import Path

import pytest
import yaml


@pytest.mark.parametrize("fault", ["none", "numpy-drift", "missing-opencv", "bad-metadata"])
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
      if [ "$FAULT" != missing-opencv ]; then echo 'opencv-python-headless==4.13.0.92'; fi
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
        capture_output=True, text=True,
    )
    assert (result.returncode == 0) == (fault == "none"), result.stdout + result.stderr
