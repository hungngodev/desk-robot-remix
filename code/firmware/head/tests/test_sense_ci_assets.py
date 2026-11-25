"""Exercise the CI gate with genuinely packed and merged synthetic asset images."""

import hashlib
import importlib.util
import json
import runpy
import struct
from pathlib import Path

import pytest

HEAD = Path(__file__).resolve().parents[1]
UPSTREAM = HEAD.parents[1] / "upstream/xiaozhi-esp32/scripts/build_default_assets.py"
SPEC = importlib.util.spec_from_file_location("sense_ci_assets", HEAD / "verify_sense_ci_assets.py")
assets = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(assets)
TABLE_OFFSET = 0x8000
PARTITION_ROWS = [
    struct.pack("<2sBBII16sI", b"\xaa\x50", kind, subtype, offset, size, name, 0)
    for kind, subtype, offset, size, name in (
        (1, 2, 0x9000, 0x4000, b"nvs"),
        (1, 0, 0xD000, 0x2000, b"otadata"),
        (1, 1, 0xF000, 0x1000, b"phy_init"),
        (0, 0x10, 0x20000, 0x2F0000, b"ota_0"),
        (0, 0x11, 0x310000, 0x2F0000, b"ota_1"),
        (1, 0x82, assets.ASSETS_OFFSET, 2 * 1024 * 1024, b"assets"),
    )
]


def _partition_table():
    data = b"".join(PARTITION_ROWS)
    checksum = hashlib.md5(data, usedforsecurity=False).digest()
    return (data + b"\xeb\xeb" + b"\xff" * 14 + checksum).ljust(0xC00, b"\xff")


@pytest.fixture
def packed_image(tmp_path):
    if not UPSTREAM.is_file():
        pytest.skip("Pinned upstream asset reader unavailable")
    upstream = runpy.run_path(str(UPSTREAM))
    font = b"synthetic font bytes"
    index = {
        "version": 1,
        "text_font": assets.FONT,
        "text_font_meta": {"charset": "common", "size": 14, "bpp": 1, "bundle": "test"},
    }
    config = tmp_path / "sdkconfig"
    config.write_text("\n".join(sorted(assets.CONFIG)) + "\n")
    component = tmp_path / "managed_components/78__xiaozhi-fonts"
    (component / "cbin").mkdir(parents=True)
    (component / "cbin" / assets.FONT).write_bytes(font)
    (component / "manifest.json").write_text('{"bundle_id":"test"}')
    build = tmp_path / "build"
    build.mkdir()
    table = _partition_table()
    (build / "partition_table").mkdir()
    (build / "partition_table/partition-table.bin").write_bytes(table)

    def write(index_bytes=None):
        if index_bytes is None:
            index_bytes = json.dumps(index).encode()
        data = upstream["pack_assets_entries"]({
            "index.json": (index_bytes, 0, 0),
            assets.FONT: (font, 0, 0),
        })
        (build / "generated_assets.bin").write_bytes(data)
        with (build / "merged-binary.bin").open("wb") as stream:
            stream.seek(TABLE_OFFSET)
            stream.write(table)
            stream.seek(assets.ASSETS_OFFSET)
            stream.write(data)
        return data

    return tmp_path, config, index, write, upstream["read_assets_entries"]


def test_valid_packed_image(packed_image):
    root, _, _, write, reader = packed_image
    data = write()
    assert assets.verify(root, reader) == len(data)


@pytest.mark.parametrize("extra", [
    "CONFIG_WAKE_WORD_DISABLED=n",
    "# CONFIG_WAKE_WORD_DISABLED is not set",
    "CONFIG_WAKE_WORD_DISABLED=y",
    'CONFIG_IDF_TARGET="esp32"',
])
def test_reject_ambiguous_required_config(packed_image, extra):
    root, config, _, write, reader = packed_image
    write()
    config.write_text(config.read_text() + extra + "\n")
    with pytest.raises(ValueError, match="configuration"):
        assets.verify(root, reader)


@pytest.mark.parametrize("version", [True, 1.0])
def test_reject_noninteger_index_version(packed_image, version):
    root, _, index, write, reader = packed_image
    index["version"] = version
    write()
    with pytest.raises(ValueError, match="version"):
        assets.verify(root, reader)


@pytest.mark.parametrize("field,value", [("size", 14.0), ("bpp", True)])
def test_reject_noninteger_font_metadata(packed_image, field, value):
    root, _, index, write, reader = packed_image
    index["text_font_meta"][field] = value
    write()
    with pytest.raises(ValueError, match="metadata"):
        assets.verify(root, reader)


@pytest.mark.parametrize("duplicate", ['"version":0,', '"text_font":"wrong.bin",'])
def test_reject_duplicate_index_fields(packed_image, duplicate):
    root, _, index, write, reader = packed_image
    write(("{" + duplicate + json.dumps(index)[1:]).encode())
    with pytest.raises(ValueError, match="duplicate"):
        assets.verify(root, reader)


def test_reject_duplicate_component_bundle(packed_image):
    root, _, _, write, reader = packed_image
    write()
    manifest = root / "managed_components/78__xiaozhi-fonts/manifest.json"
    manifest.write_text('{"bundle_id":"wrong","bundle_id":"test"}')
    with pytest.raises(ValueError, match="duplicate"):
        assets.verify(root, reader)


def test_reject_corrupted_merged_bytes(packed_image):
    root, _, _, write, reader = packed_image
    write()
    with (root / "build/merged-binary.bin").open("r+b") as stream:
        stream.seek(assets.ASSETS_OFFSET)
        stream.write(b"\xff")
    with pytest.raises(ValueError, match="Merged firmware"):
        assets.verify(root, reader)


@pytest.mark.parametrize("board", [
    "DESK_ROBOT_MODULAR_S3",
    "DESK_ROBOT_WAVESHARE_S3_CAM",
    "DESK_ROBOT_CORE_S3",
    "ESP32_S3_BOX_3",
])
def test_reject_competing_board_selection_before_asset_io(tmp_path, board):
    config = tmp_path / "sdkconfig"
    config.write_text("\n".join(sorted(assets.CONFIG)) + f"\nCONFIG_BOARD_TYPE_{board}=y\n")

    def unexpected_reader(_):
        pytest.fail("Conflicting board must be rejected before asset IO")

    with pytest.raises(ValueError, match="competing board selection"):
        assets.verify(tmp_path, unexpected_reader)


def test_inactive_alternative_board_selection_is_allowed(packed_image):
    root, config, _, write, reader = packed_image
    data = write()
    config.write_text(
        config.read_text() + "# CONFIG_BOARD_TYPE_DESK_ROBOT_MODULAR_S3 is not set\n"
    )
    assert assets.verify(root, reader) == len(data)
