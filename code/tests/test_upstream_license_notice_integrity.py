"""Preserve the exact license notices from audited upstream revisions."""

import hashlib
from pathlib import Path

import pytest

LICENSES = Path(__file__).resolve().parents[2] / "docs/licenses"

# Git blob IDs from the pinned upstream LICENSE files, not local file hashes.
# Update only after checking the corresponding new upstream revision.
NOTICE_BLOBS = (
    ("VerdureBuddyRover-MIT.txt", "063d016f711b73a19b92d17675a9fd2c42a44811"),
    ("xiaozhi-esp32-MIT.txt", "e90b55454056bdf5b7c7a48565ef7bf2893bd1e1"),
    ("xiaozhi-esp32-server-MIT.txt", "579a3d73c800727f6aef79322f126226c2937a49"),
    ("Stackchan-agent-MIT.txt", "ddd1d93f9feb78b639e74d04497bacad1ef5ae7f"),
    ("Seeed-PN532-BSD-3-Clause.txt", "30b56bb278d04d11bf857b9475dc534b32c9135c"),
)


@pytest.mark.parametrize(("filename", "expected"), NOTICE_BLOBS)
def test_upstream_license_notice_integrity(filename: str, expected: str) -> None:
    data = (LICENSES / filename).read_bytes()
    # Git checkouts may normalize line endings; the pinned PN532 blob uses CRLF.
    data = data.replace(b"\r\n", b"\n")
    if filename == "Seeed-PN532-BSD-3-Clause.txt":
        data = data.replace(b"\n", b"\r\n")
    header = f"blob {len(data)}\0".encode()
    actual = hashlib.sha1(header + data, usedforsecurity=False).hexdigest()
    assert actual == expected, f"Upstream license notice drift: {filename}"
