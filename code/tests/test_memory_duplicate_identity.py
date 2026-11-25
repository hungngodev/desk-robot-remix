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
    reopened = MemoryStore(tmp_path, ["pet_a", "pet_b"])
    assert reopened.recent("pet_a")[0].summary == "Pet A private observation"
    assert reopened.recent("pet_b") == []


@pytest.mark.parametrize("old_id,new_id", [("pet_a", "PET_A"), ("PET_A", "pet_a")])
def test_memory_restart_rejects_case_aliased_existing_database(tmp_path, old_id, new_id):
    store = MemoryStore(tmp_path, [old_id])
    assert store.remember(
        old_id, "private_note", "Private observation",
        kind="scene", source_robot=old_id, witnessed=True,
    )

    # Reject before opening SQLite, even on case-sensitive CI filesystems.
    with pytest.raises(ValueError, match="Case-aliased robot memory database"):
        MemoryStore(tmp_path, [new_id])
    assert [path.name for path in tmp_path.glob("*.sqlite3")] == [
        f"{old_id}.sqlite3",
    ]
    reopened = MemoryStore(tmp_path, [old_id, "pet_b"])
    assert reopened.recent(old_id)[0].summary == "Private observation"
    assert reopened.recent("pet_b") == []


def test_case_aliased_database_introduced_after_start_is_rejected(tmp_path):
    store = MemoryStore(tmp_path, ["pet_a"])
    path = tmp_path / "pet_a.sqlite3"
    intermediate = tmp_path / "temporary.sqlite3"
    path.rename(intermediate)
    intermediate.rename(tmp_path / "PET_A.sqlite3")

    with pytest.raises(ValueError, match="Case-aliased robot memory database"):
        store.recent("pet_a")


def test_failed_fts_rebuild_rolls_back_entire_schema_migration(tmp_path, monkeypatch):
    import sqlite3

    database = tmp_path / "robot-1.sqlite3"
    connect = sqlite3.connect
    with connect(database) as raw:
        raw.execute(
            """CREATE TABLE memories (
               event_id TEXT PRIMARY KEY, source_robot TEXT NOT NULL,
               witnessed INTEGER NOT NULL, kind TEXT NOT NULL,
               summary TEXT NOT NULL, observed_at REAL NOT NULL,
               confidence REAL NOT NULL)"""
        )
        raw.execute(
            "INSERT INTO memories VALUES (?,?,?,?,?,?,?)",
            ("old", "robot-1", 1, "touch", "Legacy private note", 1, 1),
        )

    class FailingConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if sql == "INSERT INTO memories_fts(memories_fts) VALUES ('rebuild')":
                raise sqlite3.OperationalError("injected FTS rebuild failure")
            return super().execute(sql, parameters)

    def fail_rebuild(*args, **kwargs):
        return connect(*args, **kwargs, factory=FailingConnection)

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", fail_rebuild)
        with pytest.raises(sqlite3.OperationalError, match="injected FTS rebuild failure"):
            MemoryStore(tmp_path, ["robot-1"])

    with connect(database) as raw:
        assert "relay_token" not in {
            row[1] for row in raw.execute("PRAGMA table_info(memories)")
        }
        assert raw.execute(
            "SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
        ).fetchall() == [("memories",)]
        assert raw.execute("SELECT summary FROM memories").fetchone() == (
            "Legacy private note",
        )
        assert raw.execute("PRAGMA integrity_check").fetchone() == ("ok",)

    reopened = MemoryStore(tmp_path, ["robot-1", "robot-10"])
    assert reopened.search("robot-1", "legacy")[0].event_id == "old"
    assert reopened.search("robot-10", "legacy") == []


@pytest.mark.parametrize("suffix", ["-journal", "-wal", "-shm"])
@pytest.mark.parametrize("link", ["hard", "symbolic"])
def test_memory_rejects_linked_sqlite_sidecars(tmp_path, suffix, link):
    import os

    store = MemoryStore(tmp_path, ["pet_a", "pet_b"])
    assert store.remember(
        "pet_b", "private_note", "Pet B private observation",
        kind="scene", source_robot="pet_b", witnessed=True,
    )
    peer = tmp_path / "pet_b.sqlite3"
    expected = peer.read_bytes()
    alias = tmp_path / ("pet_a.sqlite3" + suffix)
    if link == "hard":
        os.link(peer, alias)
    else:
        alias.symlink_to(peer)
    try:
        with pytest.raises(ValueError, match="memory sidecar"):
            store.remember(
                "pet_a", "new_note", "Pet A private observation",
                kind="scene", source_robot="pet_a", witnessed=True,
            )
        assert peer.read_bytes() == expected
    finally:
        alias.unlink()
    assert store.recent("pet_a") == []
    assert store.recent("pet_b")[0].summary == "Pet B private observation"
    assert MemoryStore(tmp_path, ["pet_a", "pet_b"]).count("pet_b") == 1


def test_five_pet_database_rename_cannot_relabel_private_memory(tmp_path):
    ids = [f"pet_{i}" for i in range(1, 6)]
    store = MemoryStore(tmp_path, ids)
    for robot in ids:
        assert store.remember(
            robot, "shared_event_id", f"Private observation of {robot}",
            kind="scene", source_robot=robot, witnessed=True,
        )
        assert store.set_core_fact(robot, "favorite_game", f"Private game of {robot}")

    # Ordinary renames leave two distinct regular files with one link each.
    # Neither the existing case nor hard-link guards can detect this swap.
    third = tmp_path / "pet_3.sqlite3"
    fourth = tmp_path / "pet_4.sqlite3"
    temporary = tmp_path / "temporary.sqlite3"
    third.rename(temporary)
    fourth.rename(third)
    temporary.rename(fourth)

    for robot in ("pet_3", "pet_4"):
        with pytest.raises(ValueError, match="database identity mismatch"):
            store.recent(robot)
        with pytest.raises(ValueError, match="database identity mismatch"):
            store.search(robot, "private")
        with pytest.raises(ValueError, match="database identity mismatch"):
            store.core_facts(robot)
        with pytest.raises(ValueError, match="database identity mismatch"):
            store.forget_episode(robot, "shared_event_id")
    with pytest.raises(ValueError, match="database identity mismatch"):
        MemoryStore(tmp_path, ids)

    # An unrelated pet remains usable; restoring the correct filenames
    # recovers both owners without rewriting or deleting the private rows.
    for robot in ("pet_1", "pet_2", "pet_5"):
        assert store.recent(robot)[0].source_robot == robot
    third.rename(temporary)
    fourth.rename(third)
    temporary.rename(fourth)
    reopened = MemoryStore(tmp_path, ids)
    for robot in ids:
        assert reopened.search(robot, "private")[0].summary == f"Private observation of {robot}"
        assert reopened.core_facts(robot)[0].value == f"Private game of {robot}"


def test_legacy_firsthand_provenance_cannot_be_adopted_by_wrong_pet(tmp_path):
    import sqlite3

    store = MemoryStore(tmp_path, ["pet_3"])
    assert store.remember(
        "pet_3", "private_event", "Private observation",
        kind="scene", source_robot="pet_3", witnessed=True,
    )
    original = tmp_path / "pet_3.sqlite3"
    with sqlite3.connect(original) as db:
        db.execute("DROP TABLE memory_identity")
    original.rename(tmp_path / "pet_4.sqlite3")

    with pytest.raises(ValueError, match="Legacy memory provenance"):
        MemoryStore(tmp_path, ["pet_4"])
    # The failing migration must not persist a newly assigned identity.
    with sqlite3.connect(tmp_path / "pet_4.sqlite3") as db:
        assert db.execute(
            "SELECT name FROM sqlite_master WHERE name='memory_identity'"
        ).fetchone() is None


def test_relative_memory_root_is_anchored_to_original_working_directory(
    tmp_path, monkeypatch,
):
    from pathlib import Path

    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    ids = [f"pet_{i}" for i in range(1, 6)]
    monkeypatch.chdir(first)
    original = MemoryStore(Path("private"), ids)
    assert original.set_core_fact("pet_3", "favorite_game", "Original private game")
    monkeypatch.chdir(second)
    different = MemoryStore(Path("private"), ids)
    assert different.set_core_fact("pet_3", "favorite_game", "Other private game")

    assert original.core_facts("pet_3")[0].value == "Original private game"
    assert different.core_facts("pet_3")[0].value == "Other private game"
    assert original.forget_core_fact("pet_3", "favorite_game")
    assert different.core_facts("pet_3")[0].value == "Other private game"


def test_empty_existing_identity_table_cannot_be_silently_rebound(tmp_path):
    import sqlite3

    store = MemoryStore(tmp_path, ["pet_3"])
    assert store.set_core_fact("pet_3", "favorite_game", "Private game")
    database = tmp_path / "pet_3.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute("DELETE FROM memory_identity")
    with pytest.raises(ValueError, match="database identity mismatch"):
        store.core_facts("pet_3")
    with pytest.raises(ValueError, match="database identity unavailable"):
        MemoryStore(tmp_path, ["pet_3"])
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT robot_id FROM memory_identity").fetchall() == []
        assert db.execute("SELECT value FROM core_facts").fetchone() == ("Private game",)

@pytest.mark.parametrize("directory", ["private", "private ?#%"])
def test_runtime_memory_open_does_not_recreate_missing_database(tmp_path, directory):
    import sqlite3

    root = tmp_path / directory
    store = MemoryStore(root, ["pet_a", "pet_b"])
    assert store.set_core_fact("pet_a", "favorite_game", "Original private game")
    path = root / "pet_a.sqlite3"
    saved = root / "pet_a.backup"
    path.rename(saved)

    with pytest.raises(sqlite3.OperationalError):
        store.recent("pet_a")
    assert not path.exists()
    with pytest.raises(sqlite3.OperationalError):
        store.forget_episode("pet_a", "missing")
    assert not path.exists()
    assert store.count("pet_b") == 0

    saved.rename(path)
    assert store.core_facts("pet_a")[0].value == "Original private game"
    assert store.set_core_fact("pet_a", "favorite_game", "New private game")
    assert store.core_facts("pet_a")[0].value == "New private game"
