"""Keep the pinned Stackchan license intact in source and release notices."""

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
LICENSE = "docs/licenses/Stackchan-agent-MIT.txt"
HEADER = "code/firmware/head/overlay/stackchan_behavior.hpp"
SOURCE = (
    "https://github.com/botamochi6277/stackchan-agent/blob/"
    "bfb98fb8bdb4f8ecc4b7c1c4f9bc90ee5227e613/include/Behavior.hpp"
)
# Git blob identity of LICENSE fetched at the same upstream revision.
LICENSE_BLOB = "ddd1d93f9feb78b639e74d04497bacad1ef5ae7f"


def test_stackchan_license_and_source_provenance():
    license_bytes = (ROOT / LICENSE).read_bytes()
    blob = f"blob {len(license_bytes)}\0".encode() + license_bytes
    assert hashlib.sha1(blob, usedforsecurity=False).hexdigest() == LICENSE_BLOB
    header = (ROOT / HEADER).read_bytes()
    preamble = header.split(b"#pragma once", 1)[0]
    assert b"// Source: " + SOURCE.encode() in preamble.splitlines()
    assert b"/*\n" + license_bytes + b"*/" in preamble
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    for target in (LICENSE, HEADER, SOURCE):
        assert f"]({target})" in notices
