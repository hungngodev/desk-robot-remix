"""Board planning regressions independent of an upstream checkout."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

HEAD = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("head_overlay_planning", HEAD / "install_overlay.py")
overlay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(overlay)

AEC = b"depends on USE_AUDIO_PROCESSOR && (BOARD_TYPE_ESP32_S3_BOX_3"
UART = b"uart_set_pin(kUart, 2, 1,"


@pytest.fixture
def board_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(overlay, "HERE", tmp_path)
    for folder in ("modular", "sense", "waveshare", "overlay"):
        path = tmp_path / folder
        path.mkdir()
        (path / "shared.hpp").write_bytes(folder.encode())
        (path / "ignored.bin").write_bytes(b"ignored")
    (tmp_path / "sense" / "board.md").write_bytes(b"sense documentation")
    (tmp_path / "waveshare" / "board.md").write_bytes(b"waveshare documentation")
    (tmp_path / "overlay" / "common.md").write_bytes(b"common documentation")
    (tmp_path / "overlay" / "robot_bridge.cc").write_bytes(UART)
    (tmp_path / "overlay" / "directory.hpp").mkdir()
    return tmp_path


@pytest.mark.parametrize("board,marker,label", [
    ("sense", b"DESK_ROBOT_SENSE_S3", b"Desk robot XIAO ESP32S3 Sense"),
    ("waveshare", b"DESK_ROBOT_WAVESHARE_S3_CAM", b"Desk robot Waveshare S3 CAM (hardware reference)"),
])
def test_alternate_board_plan_preserves_order_and_isolation(board_sources, monkeypatch, board, marker, label):
    original = {
        "main/Kconfig.projbuild": AEC,
        "main/identity": b"DESK_ROBOT_MODULAR_S3 Desk robot modular S3 (Freenove N16R8)",
        f'{overlay.BOARDS["modular"]}/old.cc': b"old",
    }
    snapshot = original.copy()

    def modular_plan(target, selected):
        assert target == board_sources
        assert selected == "modular"
        return original

    monkeypatch.setattr(overlay, "planned_files", modular_plan)
    plan = (overlay._sense_base_files if board == "sense" else overlay._waveshare_files)(board_sources)
    prefix = overlay.BOARDS[board]
    assert plan["main/identity"] == marker + b" " + label
    assert plan[f"{prefix}/shared.hpp"] == b"overlay"
    assert plan[f"{prefix}/board.md"] == board.encode() + b" documentation"
    assert plan[f"{prefix}/common.md"] == b"common documentation"
    assert f"{prefix}/ignored.bin" not in plan
    assert f"{prefix}/directory.hpp" not in plan
    assert not any(name.startswith(overlay.BOARDS["modular"] + "/") for name in plan)
    assert original == snapshot
    if board == "waveshare":
        assert plan[f"{prefix}/robot_bridge.cc"] == b"uart_set_pin(kUart, 43, 44,"
        assert marker in plan["main/Kconfig.projbuild"]
    else:
        assert plan[f"{prefix}/robot_bridge.cc"] == UART
        assert plan["main/Kconfig.projbuild"] == AEC


@pytest.mark.parametrize("fault", ["missing_aec", "duplicate_aec", "missing_uart", "duplicate_uart"])
def test_waveshare_anchor_error_is_unchanged(board_sources, monkeypatch, fault):
    original = {"main/Kconfig.projbuild": AEC}
    anchor = AEC if fault.endswith("aec") else UART
    invalid = b"missing" if fault.startswith("missing") else anchor + b"\n" + anchor
    if fault.endswith("aec"):
        original["main/Kconfig.projbuild"] = invalid
    else:
        (board_sources / "overlay" / "robot_bridge.cc").write_bytes(invalid)
    monkeypatch.setattr(overlay, "planned_files", lambda target, board: original)
    with pytest.raises(ValueError) as exc:
        overlay._waveshare_files(board_sources)
    assert str(exc.value) == f"Upstream patch anchor changed: {anchor.decode()[:80]!r}"


def test_modular_plan_keeps_distinct_source_filters(board_sources):
    (board_sources / "overlay" / "directory.hpp").rmdir()
    cmake = (
        b'    set(BOARD_DIR "desk-robot/desk-robot-core-s3")\n'
        b'    set(BUILTIN_TEXT_FONT font_noto_sans_basic_20_4)\n'
        b'    set(BUILTIN_ICON_FONT font_material_symbols_20_4)\n'
        b'    set(DEFAULT_EMOJI_COLLECTION noto-color-emoji_64)\n'
    )
    original = {"main/CMakeLists.txt": cmake, f"{overlay.BOARD}/old.cc": b"old"}
    plan = overlay._modular_board_files(original, "modular")
    prefix = overlay.BOARDS["modular"]
    assert plan["main/CMakeLists.txt"] == (
        b'    set(BOARD_DIR "desk-robot/desk-robot-modular-s3")\n'
        b'    set(BUILTIN_TEXT_FONT font_noto_sans_basic_14_1)\n'
        b'    set(BUILTIN_ICON_FONT font_material_symbols_14_1)\n'
    )
    assert plan[f"{prefix}/shared.hpp"] == b"overlay"
    assert f"{prefix}/common.md" not in plan
    assert f"{overlay.BOARD}/old.cc" not in plan
    assert original["main/CMakeLists.txt"] == cmake


def test_modular_camera_patch_keeps_bounds_and_lock_order(board_sources):
    common = board_sources / "main/boards/common"
    common.mkdir(parents=True)
    header = common / "esp32_camera.h"
    source = common / "esp32_camera.cc"
    header.write_text('#include "camera.h"\n    virtual bool Capture() override;\n'
                      '    std::string explain_url_;\n    std::string explain_token_;')
    source.write_text(
        '#include "esp32_camera.h"\n'
        '    explain_url_ = url;\n    explain_token_ = token;\n'
        '    if (explain_url_.empty()) {\n'
        '!explain_token_.empty()\n"Bearer " + explain_token_\n'
        'http->Open("POST", explain_url_)\n'
        '    if (current_fb_->format == PIXFORMAT_RGB565) {\n'
        '        size_t pixel_count = current_fb_->width * current_fb_->height;\n'
        'jpeg_src_len = encode_buf_size_;\n'
        'bool Esp32Camera::Capture() {\n'
        'std::expected<std::string, std::string> Esp32Camera::Explain(const std::string& question) {\n'
        'bool Esp32Camera::SetHMirror(bool enabled) {\n'
        'bool Esp32Camera::SetVFlip(bool enabled) {\n'
        'bool Esp32Camera::SetSwapBytes(bool enabled) {\n'
    )
    (board_sources / "overlay/camera_frame_bounds.hpp").write_bytes(b"bounds")
    (board_sources / "modular_snapshot.inc").write_text("snapshot")
    original = (header.read_bytes(), source.read_bytes())
    plan = {}
    overlay._patch_modular_camera(board_sources, plan)
    patched_header = plan["main/boards/common/esp32_camera.h"].decode()
    patched_source = plan["main/boards/common/esp32_camera.cc"].decode()
    assert "SnapshotJpeg() override" in patched_header
    assert "CameraExplainConfig explain_config_" in patched_header
    assert patched_source.count("camera_lock(AccessMutex())") == 5
    assert patched_source.index("ValidRgb565Frame") < patched_source.index("size_t pixel_count")
    assert "jpeg_src_len = current_fb_->len;" in patched_source
    assert patched_source.endswith("\nsnapshot\n#endif\n")
    assert (header.read_bytes(), source.read_bytes()) == original
