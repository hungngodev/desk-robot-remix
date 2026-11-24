"""Exercise the Sense post-build gate without an ESP-IDF installation."""

import json
import runpy
import struct
from pathlib import Path
from unittest.mock import Mock

import pytest

VERIFIER = runpy.run_path(str(Path(__file__).resolve().parents[1]
                              / "firmware/head/verify_sense_ci_assets.py"))
FONT = VERIFIER["FONT"]
OFFSET = VERIFIER["ASSETS_OFFSET"]
VERIFY = VERIFIER["verify"]


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
    with (root / "build/merged-binary.bin").open("wb") as stream:
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
