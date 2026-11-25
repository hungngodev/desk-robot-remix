"""Shared stdlib-only private credential reader for Mac and provisioning tools."""

import os
import re
import stat
from pathlib import Path


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
