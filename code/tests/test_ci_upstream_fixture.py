"""A matching upstream HEAD alone does not prove a clean fixture."""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/host-verification.yml"
LOCK = WORKFLOW.parents[2] / "code/upstream-lock.json"
FIXTURES = (
    ("mac-fast", "xiaozhi-esp32-server"),
    ("python-and-head-host", "xiaozhi-esp32-server"),
    ("python-and-head-host", "xiaozhi-esp32"),
    ("sense-idf", "xiaozhi-esp32"),
)


@pytest.fixture
def offline_git(tmp_path, monkeypatch):
    # Do not inherit runner-specific Git configuration or allow remote protocols.
    for key in tuple(os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    home = tmp_path / "home"
    home.mkdir()
    config = home / ".gitconfig"
    config.write_text('[protocol]\n\tallow = never\n[protocol "file"]\n\tallow = always\n')
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / "config"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_ALLOW_PROTOCOL", "file")
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")


def git(cwd, *args):
    return subprocess.check_output(["git", *args], cwd=cwd, text=True, timeout=30).strip()


def fixture_commands(lane, name):
    steps = yaml.safe_load(WORKFLOW.read_text())["jobs"][lane]["steps"]
    step = next(
        step for step in steps if f"git init upstream/{name}\n" in step.get("run", "")
    )
    assert step["working-directory"] == "code"
    # Test the real checkout commands, not the subsequent Sense overlay build.
    lines = step["run"].splitlines()
    end = next(i for i, line in enumerate(lines) if "rev-parse HEAD" in line)
    restore = "\n".join(lines[:end + 1])
    pin = re.search(r"fetch --depth=1 origin ([0-9a-f]{40})", restore)
    assert pin is not None
    assert lines[end].endswith(f' = "{pin[1]}"')
    url = re.search(r"remote add origin (https://[^\s]+)", restore)
    assert url is not None
    source = next(
        item for item in json.loads(LOCK.read_text())["repositories"]
        if item["path"] == f"upstream/{name}"
    )
    assert pin[1] == source["commit"]
    assert url[1] == source["url"]
    return restore, pin[1], url[1]


@pytest.mark.parametrize("lane,name", FIXTURES)
@pytest.mark.parametrize("stale", [False, True])
def test_upstream_restore_requires_fresh_directory(tmp_path, lane, name, stale, offline_git):
    restore, pin, url = fixture_commands(lane, name)
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
    # The remote tip must differ from the pin, or a fetch of HEAD could pass.
    (remote / "tracked.txt").write_text("newer contents\n")
    git(
        remote, "-c", "user.name=CI", "-c", "user.email=ci@example.invalid",
        "commit", "-qam", "newer",
    )
    assert git(remote, "rev-parse", "HEAD") != head
    restore = restore.replace(pin, head).replace(url, remote.as_uri())
    code = tmp_path / "code"
    code.mkdir()
    target = code / "upstream" / name
    if stale:
        target.mkdir(parents=True)
        (target / "stale.py").write_text("# untracked cached source\n")
    result = subprocess.run(
        ["bash", "-e", "-c", restore], cwd=code, capture_output=True, text=True, timeout=30,
    )
    if stale:
        assert result.returncode != 0, result.stdout + result.stderr
        assert not (target / ".git").exists()
        assert (target / "stale.py").read_text() == "# untracked cached source\n"
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert git(target, "rev-parse", "HEAD") == head
        assert (target / "tracked.txt").read_text() == "pinned contents\n"
        assert git(target, "status", "--porcelain", "--untracked-files=all") == ""
    assert not (tmp_path / "upstream").exists()


def test_cached_restore_cli_resolves_lock_relative_to_script(tmp_path, offline_git):
    code = tmp_path / "code with spaces"
    script = code / "scripts/restore_upstreams.py"
    script.parent.mkdir(parents=True)
    shutil.copyfile(LOCK.parent / "scripts/restore_upstreams.py", script)
    checkout = code / "upstream/source"
    checkout.mkdir(parents=True)
    git(checkout, "init", "-q")
    git(checkout, "config", "user.name", "CI")
    git(checkout, "config", "user.email", "ci@example.invalid")
    url = "https://github.com/example/source.git"
    git(checkout, "remote", "add", "origin", url)
    (checkout / "tracked.txt").write_text("pinned contents\n")
    git(checkout, "add", "tracked.txt")
    git(checkout, "commit", "-qm", "pinned")
    pin = git(checkout, "rev-parse", "HEAD")
    (checkout / "tracked.txt").write_text("newer contents\n")
    git(checkout, "commit", "-qam", "newer")
    (code / "upstream-lock.json").write_text(json.dumps({"repositories": [{
        "name": "source", "path": "upstream/source", "url": url, "commit": pin,
    }]}))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    result = subprocess.run(
        [sys.executable, str(script)], cwd=elsewhere, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Verified source at {pin[:12]}" in result.stdout
    assert git(checkout, "rev-parse", "HEAD") == pin
    assert (checkout / "tracked.txt").read_text() == "pinned contents\n"
    assert not git(checkout, "status", "--porcelain")
    assert not list(elsewhere.iterdir())
