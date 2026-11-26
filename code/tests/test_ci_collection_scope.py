"""Default pytest discovery must include only the configured host test suites."""

import os
import shlex
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path, PurePosixPath

import yaml


def test_default_pytest_collects_mac_and_head(tmp_path):
    code = Path(__file__).resolve().parents[1]
    shutil.copyfile(code / "pyproject.toml", tmp_path / "pyproject.toml")
    probes = {
        "tests/test_mac_probe.py": "test_mac_probe",
        "tests/extracted/extra_test.py": "test_extracted_probe",
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


def test_ci_collects_all_configured_host_suites():
    code = Path(__file__).resolve().parents[1]
    config = tomllib.loads((code / "pyproject.toml").read_text())
    roots = config["tool"]["pytest"]["ini_options"]["testpaths"]
    workflow = yaml.safe_load(
        (code.parent / ".github/workflows/host-verification.yml").read_text()
    )
    jobs = workflow["jobs"]
    step = next(
        step for step in jobs["python-and-head-host"]["steps"]
        if step.get("name") == "Host tests"
    )
    assert step["working-directory"] == "code"
    # Explicit pytest paths override testpaths. Do not allow a partial suite,
    # selection filter, or environment sync to silently replace the full run.
    assert shlex.split(step["run"]) == ["uv", "run", "--no-sync", "pytest", "-q", "-ra", *roots]
    fast = next(
        step for step in jobs["mac-fast"]["steps"]
        if step.get("name") == "Verify bounded Mac voice, memory and fleet ownership"
    )
    selected = shlex.split(fast["run"].replace(chr(92) + "\n", ""))
    assert {"tests/test_ci_collection_scope.py", "tests/test_ci_python_dependencies.py"} <= set(
        selected
    )


def test_tracked_python_test_modules_are_inside_host_suites():
    code = Path(__file__).resolve().parents[1]
    config = tomllib.loads((code / "pyproject.toml").read_text())
    roots = config["tool"]["pytest"]["ini_options"]["testpaths"]
    # Only tracked files: downloaded upstream fixtures and local virtualenvs
    # are not part of this project's Python test inventory.
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", "."], cwd=code, check=True,
        capture_output=True, timeout=30,
    )
    paths = [PurePosixPath(os.fsdecode(path)) for path in result.stdout.split(b"\0") if path]
    candidates = [
        path for path in paths
        if path.match("test_*.py") or path.match("*_test.py")
    ]
    assert PurePosixPath("tests/test_ci_collection_scope.py") in candidates
    outside = sorted(str(path) for path in candidates if not any(
        path.is_relative_to(root) for root in roots
    ))
    assert not outside, f"Tracked Python tests outside configured host suites: {outside}"
