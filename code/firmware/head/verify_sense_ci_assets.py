#!/usr/bin/env python3
"""Verify both disabled-wake Sense CI images using Xiaozhi's pinned asset reader."""

from __future__ import annotations

import argparse
import json
import runpy
import struct
from collections.abc import Callable
from pathlib import Path

FLASH_SIZE = 8 * 1024 * 1024
ASSETS_OFFSET = 0x600000
ASSETS_LIMIT = 2 * 1024 * 1024
FONT = "font_noto_sans_common_14_1.bin"
CONFIG = {
    'CONFIG_IDF_TARGET="esp32s3"',
    "CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3=y",
    "CONFIG_ESPTOOLPY_FLASHSIZE_8MB=y",
    'CONFIG_PARTITION_TABLE_CUSTOM_FILENAME="partitions/v2/8m.csv"',
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


def verify(root: Path, read_entries: Callable) -> int:
    """Fail on wrong profile, missing/corrupt resources or incorrect merged bytes."""
    config = (root / "sdkconfig").read_text(encoding="utf-8").splitlines()
    for expected in sorted(CONFIG):
        key = expected.split("=", 1)[0]
        matches = [line for line in config if line.startswith(key + "=")
                   or line == f"# {key} is not set"]
        if matches != [expected]:
            raise ValueError(f"Unexpected Sense CI configuration: {key}")
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
    with merged.open("rb") as stream:
        stream.seek(ASSETS_OFFSET)
        if stream.read(len(data)) != data:
            raise ValueError("Merged firmware does not contain generated assets at 0x600000")
    return len(data)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Prepared Xiaozhi Sense build checkout")
    args = parser.parse_args()
    upstream = runpy.run_path(str(args.root / "scripts/build_default_assets.py"))
    reader = upstream["read_assets_entries"]
    print(f"Verified {verify(args.root, reader)} asset bytes in merged Sense CI image")


if __name__ == "__main__":
    main()
