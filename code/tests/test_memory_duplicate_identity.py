"""Fleet memory identities must never silently alias the same SQLite file."""

import pytest
from desk_robot.memory import MemoryStore


@pytest.mark.parametrize("ids", [
    ["pet_a", "pet_a"],
    ("pet_a", "pet_b", "pet_a"),
    ["pet_a", "pet_b", "pet_b", "pet_c"],
    ["pet_a", "PET_A"],
    ("Pet_01", "pet_01", "pet_02"),
])
def test_duplicate_robot_memory_id_rejected_before_database_creation(tmp_path, ids):
    with pytest.raises(ValueError, match="Duplicate robot memory identities"):
        MemoryStore(tmp_path, ids)
    assert not list(tmp_path.glob("*.sqlite3"))


def test_distinct_robot_memories_still_initialize_independently(tmp_path):
    store = MemoryStore(tmp_path, ["pet_a", "pet_b"])
    assert store.robot_ids == {"pet_a", "pet_b"}
    assert store.count("pet_a") == store.count("pet_b") == 0
    assert sorted(path.name for path in tmp_path.glob("*.sqlite3")) == [
        "pet_a.sqlite3", "pet_b.sqlite3",
    ]


def test_memory_root_permissions_must_be_private_before_creating_databases(tmp_path, monkeypatch):
    import os

    root = tmp_path / "shared_memory"
    root.mkdir(mode=0o755)
    root.chmod(0o755)

    def deny_mode(path, mode):
        assert os.fspath(path) == os.fspath(root)
        assert mode == 0o700
        raise PermissionError("network share rejects chmod")

    monkeypatch.setattr(os, "chmod", deny_mode)
    with pytest.raises(PermissionError, match="Cannot protect private robot memory root"):
        MemoryStore(root, ["pet_a", "pet_b"])
    assert not list(root.glob("*.sqlite3"))
