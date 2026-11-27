"""The SQLite filesystem boundary rejects unsafe entries before database open."""

import os
import stat

import pytest
from desk_robot.private_files import validate_private_sqlite_files


@pytest.mark.parametrize("suffix", ["", "-journal", "-wal", "-shm"])
def test_private_sqlite_rejects_case_aliases(tmp_path, suffix):
    path = tmp_path / "pet_a.sqlite3"
    alias = tmp_path / ("PET_A.sqlite3" + suffix)
    alias.touch(mode=0o600)
    with pytest.raises(ValueError, match="Case-aliased"):
        validate_private_sqlite_files(path)


@pytest.mark.parametrize("suffix", ["", "-journal", "-wal", "-shm"])
@pytest.mark.parametrize("kind", ["directory", "fifo", "symlink", "hardlink"])
def test_private_sqlite_rejects_unsafe_entries(tmp_path, suffix, kind):
    path = tmp_path / "pet_a.sqlite3"
    entry = tmp_path / (path.name + suffix)
    peer = tmp_path / "pet_b.sqlite3"
    peer.write_bytes(b"private peer data")
    if kind == "directory":
        entry.mkdir()
    elif kind == "fifo":
        os.mkfifo(entry)
    elif kind == "symlink":
        entry.symlink_to(peer)
    else:
        os.link(peer, entry)
    with pytest.raises(ValueError, match="memory database|memory sidecar"):
        validate_private_sqlite_files(path)
    assert peer.read_bytes() == b"private peer data"


@pytest.mark.parametrize("suffix", ["-journal", "-wal", "-shm"])
@pytest.mark.parametrize("mode", [0o601, 0o602, 0o604, 0o610, 0o620, 0o640])
def test_private_sqlite_rejects_nonprivate_sidecar(tmp_path, suffix, mode):
    path = tmp_path / "pet_a.sqlite3"
    sidecar = tmp_path / (path.name + suffix)
    sidecar.touch()
    sidecar.chmod(mode)
    with pytest.raises(PermissionError, match="sidecar must be owner-only"):
        validate_private_sqlite_files(path)
    assert stat.S_IMODE(sidecar.stat().st_mode) == mode


@pytest.mark.parametrize("suffix", ["", "-journal", "-wal", "-shm"])
def test_private_sqlite_rejects_foreign_owner(tmp_path, monkeypatch, suffix):
    path = tmp_path / "pet_a.sqlite3"
    entry = tmp_path / (path.name + suffix)
    entry.touch(mode=0o600)
    validate_private_sqlite_files(path)
    uid = os.geteuid()
    monkeypatch.setattr(os, "geteuid", lambda: uid + 1)
    with pytest.raises(PermissionError, match="owner-owned"):
        validate_private_sqlite_files(path)


def test_private_sqlite_accepts_regular_private_files_and_legacy_main(tmp_path):
    path = tmp_path / "pet_a.sqlite3"
    validate_private_sqlite_files(path)
    path.touch()
    path.chmod(0o644)
    for suffix in ("-journal", "-wal", "-shm"):
        (tmp_path / (path.name + suffix)).touch(mode=0o600)
    validate_private_sqlite_files(path)


@pytest.mark.parametrize("second_state", ["missing", "vanishing", "replacement_ok", "replacement_hardlink"])
def test_private_sqlite_handles_transiently_unlinking_journal_sidecar(
    tmp_path, monkeypatch, second_state,
):
    path = tmp_path / "pet_a.sqlite3"
    path.touch(mode=0o600)
    journal = tmp_path / "pet_a.sqlite3-journal"
    journal.touch(mode=0o600)
    real_stat = os.stat
    calls = 0

    def flaky_stat(target, *args, **kwargs):
        nonlocal calls
        follow = kwargs.get("follow_symlinks", True)
        if not follow and os.fspath(target) == os.fspath(journal):
            st = real_stat(target, *args, **kwargs)
            calls += 1
            fields = list(st)
            if calls == 1:
                fields[3] = 0  # st_nlink == 0 mid-unlink
                return os.stat_result(fields)
            if second_state == "missing":
                raise FileNotFoundError(target)
            if second_state == "vanishing":
                fields[3] = 0
                return os.stat_result(fields)
            if second_state == "replacement_hardlink":
                fields[3] = 2
                return os.stat_result(fields)
            return st
        return real_stat(target, *args, **kwargs)

    monkeypatch.setattr(os, "stat", flaky_stat)
    if second_state == "replacement_hardlink":
        with pytest.raises(ValueError, match="linked or nonregular memory sidecar"):
            validate_private_sqlite_files(path)
    else:
        validate_private_sqlite_files(path)
    assert calls == 2
