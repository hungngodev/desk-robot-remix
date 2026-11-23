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


def test_each_pet_database_restricts_legacy_file_permissions(tmp_path, monkeypatch):
    import os
    import stat

    store = MemoryStore(tmp_path, ["pet_a", "pet_b"])
    own = tmp_path / "pet_a.sqlite3"
    peer = tmp_path / "pet_b.sqlite3"
    assert stat.S_IMODE(own.stat().st_mode) == 0o600
    assert stat.S_IMODE(peer.stat().st_mode) == 0o600
    own.chmod(0o644)
    assert store.count("pet_a") == 0
    assert stat.S_IMODE(own.stat().st_mode) == 0o600

    original = os.chmod

    def refuse_database(path, mode):
        if os.fspath(path) == os.fspath(own):
            raise PermissionError("private volume denies chmod")
        return original(path, mode)

    monkeypatch.setattr(os, "chmod", refuse_database)
    with pytest.raises(PermissionError, match="Cannot protect private robot memory database"):
        store.recent("pet_a")
    # No failure on one private file changes another robot's storage.
    assert store.recent("pet_b") == []


def test_private_memory_connections_restore_secure_delete_for_legacy_store(tmp_path):
    import sqlite3

    store = MemoryStore(tmp_path, ["pet_a"])
    database = tmp_path / "pet_a.sqlite3"
    with sqlite3.connect(database) as raw:
        raw.execute("PRAGMA secure_delete=OFF")
        assert raw.execute("PRAGMA secure_delete").fetchone()[0] == 0
    with store._connect("pet_a") as owned:
        assert owned.execute("PRAGMA secure_delete").fetchone()[0] == 1
    assert store.remember(
        "pet_a", "private_note", "A private note to correct",
        kind="scene", source_robot="pet_a", witnessed=True,
    )
    assert store.correct_episode("pet_a", "private_note", "Corrected note")
    assert store.forget_episode("pet_a", "private_note")
    assert store.count("pet_a") == 0


def test_hard_linked_database_cannot_alias_two_pets_at_boot_or_after_start(tmp_path):
    import os

    store = MemoryStore(tmp_path, ["pet_a", "pet_b"])
    assert store.remember(
        "pet_a", "private_note", "Pet A private observation",
        kind="scene", source_robot="pet_a", witnessed=True,
    )
    own = tmp_path / "pet_a.sqlite3"
    peer = tmp_path / "pet_b.sqlite3"
    peer.unlink()
    os.link(own, peer)

    # Both names now point to the same physical SQLite database. Reject
    # either owner rather than letting pet B read pet A private episodes.
    with pytest.raises(ValueError, match="hard-linked memory database"):
        store.recent("pet_b")
    with pytest.raises(ValueError, match="hard-linked memory database"):
        store.recent("pet_a")
    with pytest.raises(ValueError, match="hard-linked memory database"):
        MemoryStore(tmp_path, ["pet_a", "pet_b"])

    # The operator can remove the alias without losing the original memory.
    peer.unlink()
    assert store.recent("pet_a")[0].summary == "Pet A private observation"
    assert store.recent("pet_b") == []
