"""Exercise the upstream restorer with real disposable local Git repositories."""

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "restore_upstreams", Path(__file__).resolve().parents[1] / "scripts/restore_upstreams.py"
)
restore = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(restore)
URL = "https://github.com/example/source.git"


def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()


def repository(path):
    path.mkdir(parents=True)
    git(path, "init", "-q")
    git(path, "config", "user.name", "Test")
    git(path, "config", "user.email", "test@example.invalid")
    git(path, "remote", "add", "origin", URL)
    (path / "tracked").write_text("original")
    git(path, "add", "tracked")
    git(path, "commit", "-qm", "initial")
    return git(path, "rev-parse", "HEAD")


def configure(root, monkeypatch, commit="a" * 40, path="upstream/source", url=URL):
    monkeypatch.setattr(restore, "ROOT", root)
    (root / "upstream-lock.json").write_text(json.dumps({"repositories": [{
        "name": "source", "path": path, "url": url, "commit": commit,
    }]}))


@pytest.mark.parametrize("part", ["upstream", "upstream/source"])
@pytest.mark.parametrize("dangling", [False, True])
def test_redirected_checkout_rejected(tmp_path, monkeypatch, part, dangling):
    target = tmp_path / "victim"
    if not dangling:
        repository(target)
    link = tmp_path / part
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target, target_is_directory=True)
    configure(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match="redirected"):
        restore.main()
    assert target.exists() != dangling
    assert link.is_symlink()


@pytest.mark.parametrize("path", ["../source", "/tmp/source", "upstream/../source", "source"])
def test_path_escape_rejected(tmp_path, monkeypatch, path):
    configure(tmp_path, monkeypatch, path=path)
    with pytest.raises(RuntimeError, match="checkout path"):
        restore.main()


def test_nested_directory_cannot_use_parent_git(tmp_path, monkeypatch):
    root = tmp_path / "parent"
    original = repository(root)
    (root / "upstream/source").mkdir(parents=True)
    configure(root, monkeypatch, commit=original)
    with pytest.raises(RuntimeError, match="standalone"):
        restore.main()
    assert git(root, "rev-parse", "HEAD") == original


def test_inherited_git_directory_does_not_redirect_checkout(tmp_path, monkeypatch):
    path = tmp_path / "upstream/source"
    original = repository(path)
    victim = tmp_path / "victim"
    victim_head = repository(victim)
    configure(tmp_path, monkeypatch, commit=original)
    monkeypatch.setenv("GIT_DIR", str(victim / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(victim))
    restore.main()
    monkeypatch.delenv("GIT_DIR")
    monkeypatch.delenv("GIT_WORK_TREE")
    assert git(path, "rev-parse", "HEAD") == original
    assert git(victim, "rev-parse", "HEAD") == victim_head
    assert git(victim, "symbolic-ref", "HEAD")


def test_dirty_checkout_preserved(tmp_path, monkeypatch):
    path = tmp_path / "upstream/source"
    original = repository(path)
    configure(tmp_path, monkeypatch, commit=original)
    (path / "tracked").write_text("local edit")
    with pytest.raises(RuntimeError, match="local changes"):
        restore.main()
    assert (path / "tracked").read_text() == "local edit"


@pytest.mark.parametrize("pin", ["HEAD", "-f", "a" * 39, "g" * 40])
def test_non_commit_pin_rejected(tmp_path, monkeypatch, pin):
    configure(tmp_path, monkeypatch, commit=pin)
    with pytest.raises(RuntimeError, match="commit pin"):
        restore.main()
    assert not (tmp_path / "upstream").exists()


@pytest.mark.parametrize("url", ["ext::command", "file:///tmp/source", "--upload-pack=command"])
def test_non_public_url_rejected(tmp_path, monkeypatch, url):
    configure(tmp_path, monkeypatch, url=url)
    with pytest.raises(RuntimeError, match="repository URL"):
        restore.main()
    assert not (tmp_path / "upstream").exists()


def test_git_metadata_symlink_rejected(tmp_path, monkeypatch):
    victim = tmp_path / "victim"
    original = repository(victim)
    path = tmp_path / "upstream/source"
    path.mkdir(parents=True)
    (path / ".git").symlink_to(victim / ".git", target_is_directory=True)
    configure(tmp_path, monkeypatch, commit=original)
    with pytest.raises(RuntimeError, match="standalone"):
        restore.main()
    assert git(victim, "symbolic-ref", "HEAD")


def test_ignored_file_not_overwritten_by_checkout(tmp_path, monkeypatch):
    path = tmp_path / "upstream/source"
    repository(path)
    (path / "local-secret").write_text("upstream version")
    git(path, "add", "local-secret")
    git(path, "commit", "-qm", "add file")
    pin = git(path, "rev-parse", "HEAD")
    git(path, "checkout", "-q", "HEAD~1")
    (path / ".git/info/exclude").write_text("local-secret\n")
    (path / "local-secret").write_text("private local data")
    configure(tmp_path, monkeypatch, commit=pin)
    with pytest.raises(subprocess.CalledProcessError):
        restore.main()
    assert (path / "local-secret").read_text() == "private local data"
