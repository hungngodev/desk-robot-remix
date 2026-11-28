"""Exercise the Sense post-build gate without an ESP-IDF installation."""

import hashlib
import json
import runpy
import struct
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

VERIFIER_PATH = Path(__file__).resolve().parents[1] / "firmware/head/verify_sense_ci_assets.py"
VERIFIER = runpy.run_path(str(VERIFIER_PATH))
FONT = VERIFIER["FONT"]
OFFSET = VERIFIER["ASSETS_OFFSET"]
TABLE_OFFSET = 0x8000
TABLE_PATH = "build/partition_table/partition-table.bin"
VERIFY = VERIFIER["verify"]


# Layout from the pinned Xiaozhi partitions/v2/8m.csv, including auto-aligned ota_1.
PARTITION_ROWS = [
    struct.pack("<2sBBII16sI", b"\xaa\x50", kind, subtype, offset, size, name, 0)
    for kind, subtype, offset, size, name in (
        (1, 2, 0x9000, 0x4000, b"nvs"),
        (1, 0, 0xD000, 0x2000, b"otadata"),
        (1, 1, 0xF000, 0x1000, b"phy_init"),
        (0, 0x10, 0x20000, 0x2F0000, b"ota_0"),
        (0, 0x11, 0x310000, 0x2F0000, b"ota_1"),
        (1, 0x82, OFFSET, 2 * 1024 * 1024, b"assets"),
    )
]


def partition_table(rows):
    data = b"".join(rows)
    checksum = hashlib.md5(data, usedforsecurity=False).digest()
    return (data + b"\xeb\xeb" + b"\xff" * 14 + checksum).ljust(0xC00, b"\xff")


@pytest.fixture
def image(tmp_path):
    root = tmp_path
    (root / "build").mkdir()
    (root / "sdkconfig").write_text("\n".join(VERIFIER["CONFIG"]))
    component = root / "managed_components/78__xiaozhi-fonts"
    (component / "cbin").mkdir(parents=True)
    (component / "cbin" / FONT).write_bytes(b"font")
    (component / "manifest.json").write_text('{"bundle_id":"test-bundle"}')
    index = {
        "version": 1,
        "text_font": FONT,
        "text_font_meta": {"charset": "common", "size": 14, "bpp": 1, "bundle": "test-bundle"},
    }
    data = struct.pack("<III", 2, 0, 4) + b"data"
    (root / "build/generated_assets.bin").write_bytes(data)
    table = partition_table(PARTITION_ROWS)
    (root / TABLE_PATH).parent.mkdir()
    (root / TABLE_PATH).write_bytes(table)
    with (root / "build/merged-binary.bin").open("wb") as stream:
        stream.seek(TABLE_OFFSET)
        stream.write(table)
        stream.seek(OFFSET)
        stream.write(data)
    entries = {"index.json": (json.dumps(index).encode(), 0, 0), FONT: (b"font", 0, 0)}
    return root, Mock(return_value=entries), index


def test_valid_artifact_matches_merged_offset(image):
    root, reader, _ = image
    assert VERIFY(root, reader) == 16
    reader.assert_called_once_with(root / "build/generated_assets.bin")


@pytest.mark.parametrize("bad_size", [0, 11, 2 * 1024 * 1024 + 1])
def test_empty_truncated_and_oversized_pack_rejected(image, bad_size):
    root, reader, _ = image
    with (root / "build/generated_assets.bin").open("wb") as stream:
        stream.truncate(bad_size)
    with pytest.raises(ValueError, match="empty, truncated or exceeds"):
        VERIFY(root, reader)


def test_wrong_header_length_rejected(image):
    root, reader, _ = image
    (root / "build/generated_assets.bin").write_bytes(struct.pack("<III", 2, 0, 0) + b"data")
    with pytest.raises(ValueError, match="declared length"):
        VERIFY(root, reader)


@pytest.mark.parametrize("fault", ["font_missing", "font_corrupt", "font_meta", "stale_model"])
def test_invalid_asset_content_rejected(image, fault):
    root, reader, index = image
    entries = reader.return_value
    if fault == "font_missing":
        del entries[FONT]
    elif fault == "font_corrupt":
        entries[FONT] = (b"wrong", 0, 0)
    elif fault == "font_meta":
        index["text_font_meta"]["bundle"] = "wrong"
    else:
        index["srmodels"] = "old.bin"
    entries["index.json"] = (json.dumps(index).encode(), 0, 0)
    with pytest.raises(ValueError):
        VERIFY(root, reader)


def test_reader_checksum_failure_propagates(image):
    root, reader, _ = image
    reader.side_effect = ValueError("Assets checksum mismatch")
    with pytest.raises(ValueError, match="checksum"):
        VERIFY(root, reader)


def test_wrong_merge_bytes_rejected(image):
    root, reader, _ = image
    with (root / "build/merged-binary.bin").open("r+b") as stream:
        stream.seek(OFFSET)
        stream.write(b"bad")
    with pytest.raises(ValueError, match="does not contain generated assets"):
        VERIFY(root, reader)


def test_wrong_board_rejected(image):
    root, reader, _ = image
    (root / "sdkconfig").write_text("CONFIG_BOARD_TYPE_DESK_ROBOT_CORE_S3=y\n")
    with pytest.raises(ValueError, match="Unexpected Sense CI configuration"):
        VERIFY(root, reader)


def test_pinned_reader_and_packer_roundtrip(image):
    root, reader, _ = image
    upstream = Path(__file__).resolve().parents[1] / "upstream/xiaozhi-esp32"
    script = upstream / "scripts/build_default_assets.py"
    if not script.is_file():
        pytest.skip("Restore pinned upstream fixture for real packer integration")
    packer = runpy.run_path(str(script))
    data = packer["pack_assets_entries"](reader.return_value)
    assets = root / "build/generated_assets.bin"
    assets.write_bytes(data)
    with (root / "build/merged-binary.bin").open("r+b") as stream:
        stream.seek(OFFSET)
        stream.write(data)
    assert VERIFY(root, packer["read_assets_entries"]) == len(data)
    assets.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
    with pytest.raises(ValueError, match="checksum"):
        VERIFY(root, packer["read_assets_entries"])


@pytest.mark.parametrize(
    "fault", ["empty", "truncated", "oversized", "wrong_partition", "duplicate",
              "bad_magic", "bad_checksum", "bad_padding"]
)
def test_invalid_partition_table_rejected_even_if_merged_matches(image, fault):
    root, reader, _ = image
    table = (root / TABLE_PATH).read_bytes()
    if fault == "empty":
        table = b""
    elif fault == "truncated":
        table = table[:-1]
    elif fault == "oversized":
        table += b"\xff" * 32
    elif fault == "wrong_partition":
        asset_row = PARTITION_ROWS[-1]
        wrong_row = asset_row[:4] + struct.pack("<I", OFFSET - 0x1000) + asset_row[8:]
        table = partition_table([*PARTITION_ROWS[:-1], wrong_row])
    elif fault == "duplicate":
        table = partition_table([*PARTITION_ROWS, PARTITION_ROWS[-1]])
    elif fault == "bad_magic":
        table = partition_table([*PARTITION_ROWS, b"\x00" * 32])
    elif fault == "bad_checksum":
        position = len(PARTITION_ROWS) * 32 + 16
        table = table[:position] + bytes([table[position] ^ 1]) + table[position + 1:]
    else:
        table = table[:-1] + b"\x00"
    (root / TABLE_PATH).write_bytes(table)
    with (root / "build/merged-binary.bin").open("r+b") as stream:
        stream.seek(TABLE_OFFSET)
        stream.write(table)
    with pytest.raises(ValueError, match="[Pp]artition table"):
        VERIFY(root, reader)


def test_wrong_partition_offset_config_rejected(image):
    root, reader, _ = image
    config = root / "sdkconfig"
    config.write_text(config.read_text().replace("CONFIG_PARTITION_TABLE_OFFSET=0x8000",
                                                 "CONFIG_PARTITION_TABLE_OFFSET=0x9000"))
    with pytest.raises(ValueError, match="CONFIG_PARTITION_TABLE_OFFSET"):
        VERIFY(root, reader)


def test_wrong_merged_partition_table_rejected(image):
    root, reader, _ = image
    with (root / "build/merged-binary.bin").open("r+b") as stream:
        stream.seek(TABLE_OFFSET)
        stream.write(b"bad")
    with pytest.raises(ValueError, match="partition table at 0x8000"):
        VERIFY(root, reader)


@pytest.mark.parametrize("relative_path", ["sdkconfig", "build/generated_assets.bin",
                                           TABLE_PATH, "build/merged-binary.bin"])
def test_missing_artifact_has_clean_cli_failure(image, relative_path):
    root, reader, _ = image
    script = root / "scripts/build_default_assets.py"
    script.parent.mkdir()
    script.write_text(f"def read_assets_entries(path):\n    return {reader.return_value!r}\n")
    (root / relative_path).unlink()
    result = subprocess.run([sys.executable, str(VERIFIER_PATH), str(root)],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert "Sense CI asset verification failed:" in result.stderr
    assert relative_path in result.stderr
    assert "Traceback" not in result.stderr
    assert not result.stdout
