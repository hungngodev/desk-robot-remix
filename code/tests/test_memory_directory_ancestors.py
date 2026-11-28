"""Private per-pet SQLite storage rejects symlink aliases before creating data."""
from __future__ import annotations

import os

import pytest
from desk_robot.config import load_settings
from desk_robot.memory import MemoryStore


def test_new_memory_directory_rejects_linked_ancestor_before_mkdir(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="ancestry.*symlinks"):
        MemoryStore(alias / "private" / "memory", ["robot-01"])
    assert not (outside / "private").exists()


def test_symlinked_memory_root_and_lexical_parent_are_rejected(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root_link = tmp_path / "linked-root"
    root_link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="ancestry.*symlinks"):
        MemoryStore(root_link, ["robot-01"])
    with pytest.raises(ValueError, match="ancestry.*symlinks"):
        MemoryStore(root_link / ".." / "unapproved", ["robot-01"])
    assert not (tmp_path / "unapproved").exists()


def test_existing_memory_rechecks_parent_alias_before_sqlite_open(tmp_path):
    parent = tmp_path / "private"
    root = parent / "memories"
    store = MemoryStore(root, ["robot-01"])
    assert store.count("robot-01") == 0
    replacement = tmp_path / "old-private"
    parent.rename(replacement)
    parent.symlink_to(replacement, target_is_directory=True)
    with pytest.raises(ValueError, match="ancestry.*symlinks"):
        store.count("robot-01")


def test_loaded_memory_path_does_not_erase_configured_symlink(tmp_path):
    actual = tmp_path / "outside"
    actual.mkdir()
    (tmp_path / "alias").symlink_to(actual, target_is_directory=True)
    config = tmp_path / "robot.toml"
    config.write_text(
        'memory_dir = "alias/private"\n'
        '[[robots]]\n'
        'id = "robot-01"\n'
        'name = "Pet"\n'
        'token_env = "DESK_ROBOT_HEAD_TOKEN"\n',
        encoding="utf-8",
    )
    settings = load_settings(config)
    assert "alias" in settings.memory_dir.parts
    with pytest.raises(ValueError, match="ancestry.*symlinks"):
        MemoryStore(settings.memory_dir, ["robot-01"])
    assert not (actual / "private").exists()


def test_regular_memory_root_remains_private_and_functional(tmp_path):
    root = tmp_path / "ordinary" / "memory"
    store = MemoryStore(root, ["robot-01", "robot-02"])
    assert store.count("robot-01") == 0
    assert store.count("robot-02") == 0
    assert os.stat(root).st_mode & 0o077 == 0
    assert os.stat(root / "robot-01.sqlite3").st_mode & 0o077 == 0


@pytest.mark.parametrize("mode", [0o755, 0o777])
def test_existing_memory_rejects_relaxed_root_permissions(tmp_path, mode):
    root = tmp_path / "memory"
    store = MemoryStore(root, ["robot-01", "robot-02"])
    assert store.count("robot-01") == 0
    root.chmod(mode)
    try:
        for robot in ("robot-01", "robot-02"):
            with pytest.raises(PermissionError, match="memory root"):
                store.count(robot)
        assert root.stat().st_mode & 0o777 == mode
    finally:
        root.chmod(0o700)
    assert store.count("robot-01") == 0
    assert store.count("robot-02") == 0
