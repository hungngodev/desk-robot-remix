"""Default pytest discovery must include only the configured host test suites."""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def test_default_pytest_collects_mac_and_head(tmp_path):
    code = Path(__file__).resolve().parents[1]
    shutil.copyfile(code / "pyproject.toml", tmp_path / "pyproject.toml")
    probes = {
        "tests/test_mac_probe.py": "test_mac_probe",
        "firmware/head/tests/test_head_probe.py": "test_head_probe",
    }
    outside_scope = {
        "test_root_probe.py": "test_root_probe",
        "firmware/body/tests/test_body_probe.py": "test_body_probe",
    }
    for relative, name in (probes | outside_scope).items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"def {name}():\n    pass\n")

    env = {key: value for key, value in os.environ.items() if not key.startswith("PYTEST_")}
    env.pop("PYTHONPATH", None)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    collected = {line for line in result.stdout.splitlines() if "::" in line}
    assert collected == {f"{relative}::{name}" for relative, name in probes.items()}
