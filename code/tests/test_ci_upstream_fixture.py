"""A matching upstream HEAD alone does not prove a clean fixture."""

import re
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/host-verification.yml"
FIXTURES = (
    ("mac-fast", "xiaozhi-esp32-server"),
    ("python-and-head-host", "xiaozhi-esp32-server"),
    ("python-and-head-host", "xiaozhi-esp32"),
    ("sense-idf", "xiaozhi-esp32"),
)


def git(cwd, *args):
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


@pytest.mark.parametrize("lane,name", FIXTURES)
@pytest.mark.parametrize("stale", [False, True])
def test_upstream_restore_requires_fresh_directory(tmp_path, lane, name, stale):
    steps = yaml.safe_load(WORKFLOW.read_text())["jobs"][lane]["steps"]
    script = next(
        step["run"] for step in steps
        if f"git init upstream/{name}\n" in step.get("run", "")
    )
    # Test the real checkout commands, not the subsequent Sense overlay build.
    lines = script.splitlines()
    end = next(i for i, line in enumerate(lines) if "rev-parse HEAD" in line)
    restore = "\n".join(lines[:end + 1])
    pin = re.search(r"fetch --depth=1 origin ([0-9a-f]{40})", restore)
    assert pin is not None
    assert lines[end].endswith(f' = "{pin[1]}"')
    url = re.search(r"remote add origin (https://[^\s]+)", restore)
    assert url is not None

    remote = tmp_path / "remote"
    remote.mkdir()
    git(remote, "init", "-q")
    (remote / "tracked.txt").write_text("pinned contents\n")
    git(remote, "add", ".")
    git(
        remote, "-c", "user.name=CI", "-c", "user.email=ci@example.invalid",
        "commit", "-qm", "fixture",
    )
    head = git(remote, "rev-parse", "HEAD")
    restore = restore.replace(pin[1], head).replace(url[1], remote.as_uri())
    target = tmp_path / "upstream" / name
    if stale:
        target.mkdir(parents=True)
        (target / "stale.py").write_text("# untracked cached source\n")
    result = subprocess.run(
        ["bash", "-e", "-c", restore], cwd=tmp_path, capture_output=True, text=True,
    )
    if stale:
        assert result.returncode != 0, result.stdout + result.stderr
        assert not (target / ".git").exists()
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert git(target, "rev-parse", "HEAD") == head
        assert git(target, "status", "--porcelain", "--untracked-files=all") == ""
