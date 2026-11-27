"""Shared stdlib-only private file utilities for Mac and provisioning tools."""

import os
import re
import stat
import tempfile
from pathlib import Path

_ROBOT_ID = re.compile(r"[A-Za-z0-9_-]{1,40}\Z")
_RESERVED_ROBOT_ID = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])\Z", re.I)


def is_private_robot_id(value: object) -> bool:
    """Admit portable, unambiguous private database filename stems."""
    return (type(value) is str and _ROBOT_ID.fullmatch(value) is not None
            and _RESERVED_ROBOT_ID.fullmatch(value) is None)


def validate_private_directory_ancestry(path: Path) -> None:
    """Check lexical ancestors before directory creation or private SQLite access."""
    if "\x00" in os.fspath(path):
        raise ValueError("Memory root must not contain null bytes")
    # Inspect outermost first, without resolving aliases or discarding '..'.
    for directory in (*reversed(path.parents), path):
        try:
            info = directory.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            raise ValueError("Memory root ancestry must not contain symlinks")
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("Memory root ancestry must contain only directories")
        if (info.st_mode & stat.S_IWOTH) and not (info.st_mode & stat.S_ISVTX):
            raise PermissionError(
                "Memory root ancestry must not contain non-sticky world-writable directories"
            )


def replace_private_text(path: Path, contents: str) -> None:
    """Atomically replace text in a trusted directory with a fresh 0600 file.

    Concurrent writers publish whole files (last replacement wins). This is not
    an exclusive evidence creator or a directory-entry power-loss guarantee.
    """
    stream = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=".desk-robot-", delete=False,
    )
    temporary = Path(stream.name)
    try:
        with stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            # Report cleanup failure without masking the primary exception
            # (including cancellation) or exposing the temporary path.
            exc.add_note("Private temporary file cleanup failed")
        raise


def read_private_text(path: Path, *, missing_ok: bool = False) -> str:
    """Read bounded owner-only text without following a leaf symlink."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        if missing_ok:
            return ""
        raise
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Credentials must be a regular file")
        if info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError("Credentials must be owner-only (chmod 600)")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(65537)
    finally:
        os.close(fd)
    if len(raw) > 65536:
        raise ValueError("Credential file is too large")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("Credentials must be UTF-8") from None


def read_private_env(path: Path) -> dict[str, str]:
    """Parse all entries before any caller imports credentials into its environment."""
    content = read_private_text(path, missing_ok=True)
    values: dict[str, str] = {}
    for line in content.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if (
            not sep or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)
            or not value.strip() or "\x00" in value or key in values
        ):
            raise ValueError("Credential file contains a malformed or duplicate entry")
        values[key] = value
    return values


def validate_private_sqlite_files(path: Path) -> None:
    """Reject existing unsafe database and sidecar entries before SQLite opens them."""
    names = (path.name, *(path.name + suffix for suffix in ("-journal", "-wal", "-shm")))
    spellings = {name.casefold(): name for name in names}
    for entry in path.parent.iterdir():
        expected = spellings.get(entry.name.casefold())
        if expected is not None and entry.name != expected:
            raise ValueError("Case-aliased robot memory database or sidecar")
    for name in names:
        candidate = path.parent / name
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if name != path.name and stat.S_ISREG(info.st_mode) and info.st_nlink == 0:
            # Concurrent SQLite rollback-journal unlink can transiently expose
            # st_nlink == 0 under lockless RCU lstat() on Linux. Re-stat once and
            # treat an unlinked regular sidecar as gone while rejecting replacements.
            try:
                info = candidate.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISREG(info.st_mode) and info.st_nlink == 0:
                continue
        if name == path.name:
            if stat.S_ISLNK(info.st_mode):
                raise ValueError("Refusing symlinked memory database")
            if info.st_nlink > 1:
                raise ValueError("Refusing hard-linked memory database")
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("Refusing nonregular memory database")
        elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("Refusing linked or nonregular memory sidecar")
        if info.st_uid != os.geteuid():
            raise PermissionError("Robot memory database and sidecars must be owner-owned")
        if name != path.name and info.st_mode & 0o077:
            raise PermissionError("Robot memory sidecar must be owner-only")
