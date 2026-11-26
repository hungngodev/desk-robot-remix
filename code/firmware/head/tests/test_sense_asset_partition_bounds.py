"""Validate asset partition isolation without requiring upstream build artifacts."""

import hashlib
import importlib.util
from pathlib import Path

import pytest

HEAD = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("sense_ci_assets", HEAD / "verify_sense_ci_assets.py")
assets = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(assets)


def partition_table(offset, size):
    entry = assets.PARTITION_ENTRY
    rows = entry.pack(b"\xaa\x50", 0, 0x11, offset, size, b"ota_1", 0)
    rows += entry.pack(
        b"\xaa\x50", 1, 0x82, assets.ASSETS_OFFSET, assets.ASSETS_LIMIT, b"assets", 0,
    )
    checksum = hashlib.md5(rows, usedforsecurity=False).digest()
    return (rows + b"\xeb\xeb" + b"\xff" * 14 + checksum).ljust(0xC00, b"\xff")


@pytest.mark.parametrize("offset,size", [
    (0x310000, 0x2F0000),
    (0x300000, 0x1000),
])
def test_nonoverlapping_partition_is_allowed(tmp_path, offset, size):
    path = tmp_path / "partition-table.bin"
    table = partition_table(offset, size)
    path.write_bytes(table)
    assert assets.read_partition_table(path) == table


@pytest.mark.parametrize("offset,size", [
    (0x310000, 0x2F1000),
    (0x600000, 0x1000),
    (0x7FF000, 0x1000),
])
def test_reject_partition_overlapping_assets_even_with_valid_md5(tmp_path, offset, size):
    path = tmp_path / "partition-table.bin"
    path.write_bytes(partition_table(offset, size))
    with pytest.raises(ValueError, match="overlaps assets"):
        assets.read_partition_table(path)
