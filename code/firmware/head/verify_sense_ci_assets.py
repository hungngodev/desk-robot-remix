#!/usr/bin/env python3
"""Verify both disabled-wake Sense CI images using Xiaozhi's pinned asset reader."""

from __future__ import annotations

import argparse
import hashlib
import json
import runpy
import struct
from collections.abc import Callable
from pathlib import Path

FLASH_SIZE = 8 * 1024 * 1024
PARTITION_TABLE_OFFSET = 0x8000
PARTITION_TABLE_LENGTH = 0xC00
PARTITION_ENTRY = struct.Struct("<2sBBII16sI")
PARTITION_MD5_PREFIX = b"\xeb\xeb" + b"\xff" * 14
PARTITION_END = b"\xff" * PARTITION_ENTRY.size
ASSETS_OFFSET = 0x600000
ASSETS_LIMIT = 2 * 1024 * 1024
FONT = "font_noto_sans_common_14_1.bin"
CONFIG = {
    'CONFIG_IDF_TARGET="esp32s3"',
    "CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3=y",
    "CONFIG_ESPTOOLPY_FLASHSIZE_8MB=y",
    'CONFIG_PARTITION_TABLE_CUSTOM_FILENAME="partitions/v2/8m.csv"',
    "CONFIG_PARTITION_TABLE_OFFSET=0x8000",
    "CONFIG_FLASH_DEFAULT_ASSETS=y",
    "CONFIG_WAKE_WORD_DISABLED=y",
}


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Invalid asset JSON: duplicate field")
        result[key] = value
    return result


def read_partition_table(path: Path) -> bytes:
    """Check the selected asset partition, not the entire ESP-IDF flash layout.

    Format: ESP-IDF v6.1 components/partition_table/gen_esp32part.py.
    Layout: pinned Xiaozhi partitions/v2/8m.csv.
    """
    with path.open("rb") as stream:
        table = stream.read(PARTITION_TABLE_LENGTH + 1)
    if len(table) != PARTITION_TABLE_LENGTH:
        raise ValueError("Partition table binary must contain exactly 0xC00 bytes")
    matches = []
    for position in range(0, len(table), PARTITION_ENTRY.size):
        row = table[position:position + PARTITION_ENTRY.size]
        if row == PARTITION_END:
            padding = table[position:]
            break
        if row[:16] == PARTITION_MD5_PREFIX:
            checksum = hashlib.md5(table[:position], usedforsecurity=False).digest()
            if row[16:] != checksum:
                raise ValueError("Partition table MD5 checksum mismatch")
            padding = table[position + PARTITION_ENTRY.size:]
            break
        magic, kind, subtype, offset, size, name, flags = PARTITION_ENTRY.unpack(row)
        if magic != b"\xaa\x50":
            raise ValueError("Partition table contains an invalid entry")
        if name.split(b"\0", 1)[0] == b"assets":
            matches.append((kind, subtype, offset, size, flags))
    else:
        raise ValueError("Partition table is missing an end marker")
    if not padding or padding != b"\xff" * len(padding):
        raise ValueError("Partition table has invalid end padding")
    if matches != [(1, 0x82, ASSETS_OFFSET, ASSETS_LIMIT, 0)]:
        raise ValueError("Partition table must define one 2 MiB assets SPIFFS at 0x600000")
    return table


def verify(root: Path, read_entries: Callable) -> int:
    """Fail on wrong profile, missing/corrupt resources or incorrect merged bytes."""
    config = (root / "sdkconfig").read_text(encoding="utf-8").splitlines()
    for expected in sorted(CONFIG):
        key = expected.split("=", 1)[0]
        matches = [line for line in config if line.startswith(key + "=")
                   or line == f"# {key} is not set"]
        if matches != [expected]:
            raise ValueError(f"Unexpected Sense CI configuration: {key}")
    # A Sense flag alone is insufficient evidence of an exclusive board choice.
    selected_boards = [line for line in config
                       if line.startswith("CONFIG_BOARD_TYPE_") and line.endswith("=y")]
    if selected_boards != ["CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3=y"]:
        raise ValueError("Unexpected Sense CI configuration: competing board selection")
    assets = root / "build/generated_assets.bin"
    if not 12 <= assets.stat().st_size <= ASSETS_LIMIT:
        raise ValueError("Asset image is empty, truncated or exceeds 2 MiB")
    data = assets.read_bytes()
    if struct.unpack_from("<III", data)[2] != len(data) - 12:
        raise ValueError("Asset image declared length differs from packed bytes")
    entries = read_entries(assets)
    if "index.json" not in entries:
        raise ValueError("Missing asset index.json")
    index = json.loads(entries["index.json"][0], object_pairs_hook=unique_object)
    if (not isinstance(index, dict) or type(index.get("version")) is not int
            or index["version"] != 1):
        raise ValueError("Invalid asset index version")
    if index.get("text_font") != FONT or FONT not in entries:
        raise ValueError("Required Sense common font missing from asset index or image")
    font_root = root / "managed_components/78__xiaozhi-fonts"
    font = (font_root / "cbin" / FONT).read_bytes()
    if not font or entries[FONT][0] != font:
        raise ValueError("Packed font differs from locked component resource")
    manifest = json.loads((font_root / "manifest.json").read_text(encoding="utf-8"),
                          object_pairs_hook=unique_object)
    bundle = manifest.get("bundle_id") if isinstance(manifest, dict) else None
    meta = index.get("text_font_meta")
    if (not isinstance(bundle, str) or not bundle or not isinstance(meta, dict)
            or type(meta.get("size")) is not int or type(meta.get("bpp")) is not int
            or meta != {"charset": "common", "size": 14, "bpp": 1, "bundle": bundle}):
        raise ValueError("Packed font metadata differs from Sense component resource")
    if "srmodels" in index or "multinet_model" in index or "srmodels.bin" in entries:
        raise ValueError("Disabled wake-word image contains stale speech models")
    merged = root / "build/merged-binary.bin"
    if not ASSETS_OFFSET + len(data) <= merged.stat().st_size <= FLASH_SIZE:
        raise ValueError("Merged image is truncated or exceeds 8 MiB")
    table = read_partition_table(root / "build/partition_table/partition-table.bin")
    with merged.open("rb") as stream:
        stream.seek(PARTITION_TABLE_OFFSET)
        if stream.read(len(table)) != table:
            raise ValueError("Merged firmware does not contain partition table at 0x8000")
        stream.seek(ASSETS_OFFSET)
        if stream.read(len(data)) != data:
            raise ValueError("Merged firmware does not contain generated assets at 0x600000")
    return len(data)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Prepared Xiaozhi Sense build checkout")
    args = parser.parse_args()
    try:
        upstream = runpy.run_path(str(args.root / "scripts/build_default_assets.py"))
        reader = upstream.get("read_assets_entries")
        if not callable(reader):
            raise ValueError("Pinned asset reader missing from scripts/build_default_assets.py")
        size = verify(args.root, reader)
    except (OSError, ValueError, ImportError) as exc:
        parser.exit(1, f"Sense CI asset verification failed: {exc}\n")
    print(f"Verified {size} asset bytes and partition table in merged Sense CI image")


if __name__ == "__main__":
    main()
