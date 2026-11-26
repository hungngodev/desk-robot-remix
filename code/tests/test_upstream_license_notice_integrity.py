"""Preserve the exact license notices from audited upstream revisions."""

import hashlib
from configparser import ConfigParser
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
    ("ld2410-LGPL-2.1.txt", "8000a6faacf471c537530805ab29523c7732e11a"),
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


def test_ld2410_pin_matches_distribution_notice() -> None:
    root = LICENSES.parents[1]
    config = ConfigParser(interpolation=None)
    config.read(root / "code/firmware/room_station/platformio.ini")
    dependencies = config["env"]["lib_deps"].splitlines()
    assert [dep for dep in dependencies if "ncmreynolds/ld2410" in dep] == [
        "https://github.com/ncmreynolds/ld2410.git#v0.2.2"
    ]
    notice = (root / "THIRD_PARTY_NOTICES.md").read_text().split(
        "- Room station mmWave presence library", 1
    )[1].split("\n- ", 1)[0]
    assert "`ncmreynolds/ld2410` `v0.2.2`" in notice
    assert "https://github.com/ncmreynolds/ld2410/blob/v0.2.2/LICENSE" in notice
    assert "[GNU LGPL-2.1](docs/licenses/ld2410-LGPL-2.1.txt)" in notice
    assert "Section 6(a)" in notice
