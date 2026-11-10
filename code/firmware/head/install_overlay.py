#!/usr/bin/env python3
"""Apply a version-pinned, reversible Xiaozhi board overlay; never changes the source clone."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import subprocess
from pathlib import Path

PIN = "c435f99a88066029ec2dbd2d758c8cc9d051565b"
BOARD = "main/boards/desk-robot/desk-robot-core-s3"
BOARDS = {
    "cores3": BOARD,
    "modular": "main/boards/desk-robot/desk-robot-modular-s3",
    "sense": "main/boards/desk-robot/desk-robot-sense-s3",
    "waveshare": "main/boards/desk-robot/desk-robot-waveshare-s3-cam",
}
MARKER = ".desk-robot-head-overlay.json"
HERE = Path(__file__).resolve().parent


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise ValueError(f"Upstream patch anchor changed: {old[:80]!r}")
    return text.replace(old, new, 1)


def cores3_files(target: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    stock = target / "main/boards/m5stack/core-s3"
    for name in ("config.h", "cores3_audio_codec.h", "cores3_audio_codec.cc"):
        files[f"{BOARD}/{name}"] = (stock / name).read_bytes()
    source = (stock / "m5stack_core_s3.cc").read_text()
    source = source.replace("M5StackCoreS3Board", "DeskRobotCoreS3Board")
    source = replace_once(
        source, '#include "wifi_board.h"', '#include "wifi_board.h"\n#include "robot_bridge.h"'
    )
    source = replace_once(
        source,
        "    virtual AudioCodec* GetAudioCodec() override {",
        """    void StartNetwork() override {
        // WiFi initialization creates lwIP before HTTP sockets can be opened.
        // The constructor has already initialized the stock camera/display/audio.
        WifiBoard::StartNetwork();
        static desk_robot::Bridge robot_bridge(camera_);
        static std::once_flag bridge_once;
        std::call_once(bridge_once, [] { robot_bridge.Start(); });
    }

    virtual AudioCodec* GetAudioCodec() override {""",
    )
    files[f"{BOARD}/desk_robot_core_s3.cc"] = source.encode()
    for path in (HERE / "overlay").iterdir():
        if path.suffix in (".h", ".cc", ".hpp"):
            files[f"{BOARD}/{path.name}"] = path.read_bytes()
    config = json.loads((stock / "config.json").read_text())
    config["manufacturer"] = "desk-robot"
    config["type"] = "desk-robot-core-s3"
    config["builds"][0]["name"] = "desk-robot-core-s3"
    config["builds"][0]["sdkconfig_append"].extend(
        [
            'CONFIG_DESK_ROBOT_ID="robot-01"',
            'CONFIG_DESK_ROBOT_TOKEN=""',
        ]
    )
    files[f"{BOARD}/config.json"] = (json.dumps(config, indent=2) + "\n").encode()
    files[f"{BOARD}/README.md"] = (HERE / "BOARD_README.md").read_bytes()

    path = "main/Kconfig.projbuild"
    text = (target / path).read_text()
    text = replace_once(
        text,
        "    config BOARD_TYPE_DF_S3_AI_CAM\n",
        '    config BOARD_TYPE_DESK_ROBOT_CORE_S3\n        bool "Desk robot CoreS3 Lite"\n        depends on IDF_TARGET_ESP32S3\n    config BOARD_TYPE_DF_S3_AI_CAM\n',
    )
    text += """\nmenu "Desk robot private settings"
    depends on BOARD_TYPE_DESK_ROBOT_CORE_S3
config DESK_ROBOT_ID
    string "Unique robot ID"
    default "robot-01"
config DESK_ROBOT_TOKEN
    string "Private LAN bearer token (32..128 characters; empty disables robot bridge)"
    default ""
config DESK_ROBOT_DIRECT_MOTION_TOOLS
    bool "Expose low-level drive/lift/grip MCP tools (bench debugging only)"
    default n
endmenu
"""
    files[path] = text.encode()
    path = "main/CMakeLists.txt"
    text = (target / path).read_text()
    branch = """elseif(CONFIG_BOARD_TYPE_DESK_ROBOT_CORE_S3)
    set(BOARD_DIR "desk-robot/desk-robot-core-s3")
    set(BUILTIN_TEXT_FONT font_noto_sans_basic_20_4)
    set(BUILTIN_ICON_FONT font_material_symbols_20_4)
    set(DEFAULT_EMOJI_COLLECTION noto-color-emoji_64)
"""
    text = replace_once(
        text,
        "elseif(CONFIG_BOARD_TYPE_M5STACK_CORE_S3)\n",
        branch + "elseif(CONFIG_BOARD_TYPE_M5STACK_CORE_S3)\n",
    )
    text = replace_once(
        text,
        'set(MAIN_PRIV_REQUIRES_EXTRA "")',
        'set(MAIN_PRIV_REQUIRES_EXTRA "")\nif(CONFIG_BOARD_TYPE_DESK_ROBOT_CORE_S3)\n    list(APPEND MAIN_PRIV_REQUIRES_EXTRA esp_http_server)\nendif()',
    )
    files[path] = text.encode()

    path = "main/boards/common/camera.h"
    text = (target / path).read_text()
    text = replace_once(
        text,
        "#include <expected>",
        '#include <expected>\n#include "sdkconfig.h"\n#ifdef CONFIG_BOARD_TYPE_DESK_ROBOT_CORE_S3\n#include <mutex>\n#include <vector>\n#endif',
    )
    text = replace_once(
        text,
        "    virtual ~Camera() = default;",
        """    virtual ~Camera() = default;
#ifdef CONFIG_BOARD_TYPE_DESK_ROBOT_CORE_S3
    // Capture+Explain must hold the same lock as HTTP snapshots across both calls.
    std::recursive_mutex& AccessMutex() { return access_mutex_; }
    virtual std::expected<std::vector<uint8_t>, std::string> SnapshotJpeg() {
        return std::unexpected("Snapshot not supported by this camera");
    }
private:
    std::recursive_mutex access_mutex_;
public:
#endif""",
    )
    files[path] = text.encode()
    path = "main/boards/common/esp_video.h"
    text = (target / path).read_text()
    text = replace_once(
        text,
        "    virtual bool Capture();",
        "    virtual bool Capture();\n#ifdef CONFIG_BOARD_TYPE_DESK_ROBOT_CORE_S3\n    std::expected<std::vector<uint8_t>, std::string> SnapshotJpeg() override;\n#endif",
    )
    files[path] = text.encode()
    path = "main/boards/common/esp_video.cc"
    text = (target / path).read_text()
    for anchor in (
        "bool EspVideo::Capture() {",
        "std::expected<std::string, std::string> EspVideo::Explain(const std::string& question) {",
    ):
        text = replace_once(
            text,
            anchor,
            anchor
            + "\n#ifdef CONFIG_BOARD_TYPE_DESK_ROBOT_CORE_S3\n    std::lock_guard<std::recursive_mutex> camera_lock(AccessMutex());\n#endif",
        )
    text += """
#ifdef CONFIG_BOARD_TYPE_DESK_ROBOT_CORE_S3
std::expected<std::vector<uint8_t>, std::string> EspVideo::SnapshotJpeg() {
    std::lock_guard<std::recursive_mutex> camera_lock(AccessMutex());
    if (!Capture() || !frame_.data || !frame_.len)
        return std::unexpected("Fresh camera capture failed");
    uint8_t* jpeg = nullptr;
    size_t len = 0;
    const bool ok = image_to_jpeg(frame_.data, frame_.len, frame_.width, frame_.height,
                                  frame_.format, 80, &jpeg, &len);
    if (!ok || !jpeg || len < 4 || len > 512 * 1024) {
        free(jpeg);
        return std::unexpected("JPEG encoding failed");
    }
    std::vector<uint8_t> result(jpeg, jpeg + len);
    free(jpeg);
    return result;
}
#endif
"""
    files[path] = text.encode()
    path = "main/mcp_server.cc"
    text = (target / path).read_text()
    text = replace_once(
        text,
        "                    if (!camera->Capture()) {",
        "#ifdef CONFIG_BOARD_TYPE_DESK_ROBOT_CORE_S3\n                    std::lock_guard<std::recursive_mutex> camera_lock(camera->AccessMutex());\n#endif\n                    if (!camera->Capture()) {",
    )
    files[path] = text.encode()
    return files


def planned_files(target: Path, board: str = "cores3") -> dict[str, bytes]:
    """Reuse the bridge/locking overlay, replacing only the selected board adapter."""
    if board not in BOARDS:
        raise ValueError(f"Unknown board: {board}")
    if board == "waveshare":
        # Keep all existing variants unchanged. This physical-reference candidate
        # reuses their common camera/HTTP locking, but no Sense PDM adapter.
        files = {
            name: data.replace(b"DESK_ROBOT_MODULAR_S3", b"DESK_ROBOT_WAVESHARE_S3_CAM")
            .replace(
                b"Desk robot modular S3 (Freenove N16R8)",
                b"Desk robot Waveshare S3 CAM (hardware reference)",
            )
            .replace(b"desk-robot/desk-robot-modular-s3", b"desk-robot/desk-robot-waveshare-s3-cam")
            for name, data in planned_files(target, "modular").items()
            if not name.startswith(BOARDS["modular"] + "/")
        }
        for folder in (HERE / "waveshare", HERE / "overlay"):
            for path in folder.iterdir():
                if path.is_file() and path.suffix in (".cc", ".h", ".hpp", ".json", ".md"):
                    files[f"{BOARDS[board]}/{path.name}"] = path.read_bytes()
        path = "main/Kconfig.projbuild"
        files[path] = replace_once(
            files[path].decode(),
            "depends on USE_AUDIO_PROCESSOR && (BOARD_TYPE_ESP32_S3_BOX_3",
            "depends on USE_AUDIO_PROCESSOR && (BOARD_TYPE_DESK_ROBOT_WAVESHARE_S3_CAM || BOARD_TYPE_ESP32_S3_BOX_3",
        ).encode()
        path = f"{BOARDS[board]}/robot_bridge.cc"
        files[path] = replace_once(
            files[path].decode(), "uart_set_pin(kUart, 2, 1,", "uart_set_pin(kUart, 43, 44,"
        ).encode()
        return files
    if board == "sense":
        # Reuse the tested common camera/bridge changes without changing either
        # existing board adapter or its separate build copy.
        files = {
            name: data.replace(b"DESK_ROBOT_MODULAR_S3", b"DESK_ROBOT_SENSE_S3")
            .replace(b"Desk robot modular S3 (Freenove N16R8)", b"Desk robot XIAO ESP32S3 Sense")
            .replace(b"desk-robot/desk-robot-modular-s3", b"desk-robot/desk-robot-sense-s3")
            for name, data in planned_files(target, "modular").items()
            if not name.startswith(BOARDS["modular"] + "/")
        }
        for folder in (HERE / "sense", HERE / "overlay"):
            for path in folder.iterdir():
                if path.is_file() and path.suffix in (".cc", ".h", ".hpp", ".json", ".md"):
                    files[f"{BOARDS[board]}/{path.name}"] = path.read_bytes()
        # Only Sense has a real playback reference. Permit Xiaozhi's existing
        # ESP-SR AFE device AEC for this exact board, without enabling it for
        # any other profile or modifying the pristine upstream clone.
        path = "main/Kconfig.projbuild"
        files[path] = replace_once(
            files[path].decode(),
            "depends on USE_AUDIO_PROCESSOR && (BOARD_TYPE_ESP32_S3_BOX_3",
            "depends on USE_AUDIO_PROCESSOR && (BOARD_TYPE_DESK_ROBOT_SENSE_S3 || BOARD_TYPE_ESP32_S3_BOX_3",
        ).encode()
        # Add only to the selected Sense menu. The upstream remains untouched.
        files[path] = replace_once(
            files[path].decode(),
            'config DESK_ROBOT_DIRECT_MOTION_TOOLS\n    bool "Expose low-level drive/lift/grip MCP tools (bench debugging only)"\n    default n\nendmenu\n',
            'config DESK_ROBOT_DIRECT_MOTION_TOOLS\n    bool "Expose low-level drive/lift/grip MCP tools (bench debugging only)"\n    default n\nconfig DESK_ROBOT_AEC_DELAY_MS\n    int "Sense playback reference delay in milliseconds (measure physically)"\n    range 0 250\n    default 90\nendmenu\n',
        ).encode()
        # Urgent stop is an extension to the existing Xiaozhi TTS state event,
        # not a second decoder or audio transport. Normal TTS stops retain the
        # upstream behavior; flush=true explicitly discards queued decoder PCM
        # and disables I2S TX so its DMA no longer plays obsolete audio.
        path = "main/application.cc"
        text = (target / path).read_text()
        text = replace_once(
            text,
            """} else if (strcmp(state->valuestring, "stop") == 0) {
                Schedule([this]() {
                    if (GetDeviceState() == kDeviceStateSpeaking) {""",
            """} else if (strcmp(state->valuestring, "stop") == 0) {
                const bool urgent_flush = cJSON_IsTrue(cJSON_GetObjectItem(root, "flush"));
                Schedule([this, urgent_flush]() {
                    if (urgent_flush) {
                        audio_service_.ResetDecoder();
                        Board::GetInstance().GetAudioCodec()->EnableOutput(false);
                    }
                    if (GetDeviceState() == kDeviceStateSpeaking) {""",
        )
        files[path] = text.encode()
        return files
    files = cores3_files(target)
    if board == "cores3":
        return files

    # Keep the original CoreS3 source and build copy independent. The selected
    # integration guard is used by camera.h, EspVideo and the MCP capture lock.
    files = {
        name: data.replace(b"CONFIG_BOARD_TYPE_DESK_ROBOT_CORE_S3", b"CONFIG_BOARD_TYPE_DESK_ROBOT_MODULAR_S3")
        .replace(b"BOARD_TYPE_DESK_ROBOT_CORE_S3", b"BOARD_TYPE_DESK_ROBOT_MODULAR_S3")
        .replace(b'Desk robot CoreS3 Lite', b'Desk robot modular S3 (Freenove N16R8)')
        .replace(b"desk-robot/desk-robot-core-s3", b"desk-robot/desk-robot-modular-s3")
        for name, data in files.items()
        if not name.startswith(BOARD + "/")
    }
    cmake = files["main/CMakeLists.txt"].decode()
    cmake = replace_once(
        cmake,
        '    set(BOARD_DIR "desk-robot/desk-robot-modular-s3")\n'
        '    set(BUILTIN_TEXT_FONT font_noto_sans_basic_20_4)\n'
        '    set(BUILTIN_ICON_FONT font_material_symbols_20_4)\n'
        '    set(DEFAULT_EMOJI_COLLECTION noto-color-emoji_64)\n',
        '    set(BOARD_DIR "desk-robot/desk-robot-modular-s3")\n'
        '    set(BUILTIN_TEXT_FONT font_noto_sans_basic_14_1)\n'
        '    set(BUILTIN_ICON_FONT font_material_symbols_14_1)\n',
    )
    files["main/CMakeLists.txt"] = cmake.encode()
    for path in (HERE / "modular").iterdir():
        if path.is_file() and path.suffix in (".cc", ".h", ".hpp", ".json", ".md"):
            files[f"{BOARDS[board]}/{path.name}"] = path.read_bytes()
    for path in (HERE / "overlay").iterdir():
        if path.suffix in (".h", ".cc", ".hpp"):
            files[f"{BOARDS[board]}/{path.name}"] = path.read_bytes()

    guard = "#ifdef CONFIG_BOARD_TYPE_DESK_ROBOT_MODULAR_S3"
    path = "main/boards/common/esp32_camera.h"
    header = (target / path).read_text()
    header = replace_once(
        header, "    virtual bool Capture() override;",
        "    virtual bool Capture() override;\n" + guard +
        "\n    std::expected<std::vector<uint8_t>, std::string> SnapshotJpeg() override;\n#endif",
    )
    files[path] = header.encode()
    path = "main/boards/common/esp32_camera.cc"
    source = (target / path).read_text()
    for anchor in (
        "bool Esp32Camera::Capture() {",
        "std::expected<std::string, std::string> Esp32Camera::Explain(const std::string& question) {",
        "bool Esp32Camera::SetHMirror(bool enabled) {",
        "bool Esp32Camera::SetVFlip(bool enabled) {",
        "bool Esp32Camera::SetSwapBytes(bool enabled) {",
    ):
        source = replace_once(source, anchor, anchor + "\n" + guard +
                              "\n    std::lock_guard<std::recursive_mutex> camera_lock(AccessMutex());\n#endif")
    source += "\n" + guard + "\n" + (HERE / "modular_snapshot.inc").read_text() + "\n#endif\n"
    files[path] = source.encode()
    return files


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def remove(target: Path) -> None:
    marker = target / MARKER
    if not marker.exists():
        return
    state = json.loads(marker.read_text())
    for name, info in state.items():
        path = target / name
        if not path.is_file() or digest(path.read_bytes()) != info["sha256"]:
            raise ValueError(f"Refusing removal: overlaid file was changed: {name}")
    for name, info in state.items():
        path = target / name
        if info["original"] is None:
            path.unlink()
        else:
            path.write_bytes(base64.b64decode(info["original"]))
    marker.unlink()
    for name in BOARDS.values():
        board = target / name
        if board.is_dir() and not any(board.iterdir()):
            board.rmdir()


def apply(target: Path, board: str = "cores3") -> None:
    if board not in BOARDS:
        raise ValueError(f"Unknown board: {board}")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=target, text=True).strip()
    if head != PIN:
        raise ValueError(f"Requires Xiaozhi commit {PIN}, found {head}")
    marker = target / MARKER
    if marker.exists():
        state = json.loads(marker.read_text())
        if not any(name.startswith(BOARDS[board] + "/") for name in state):
            raise ValueError("A different board overlay is installed; use a separate build copy")
        for name, info in state.items():
            path = target / name
            if not path.is_file() or digest(path.read_bytes()) != info["sha256"]:
                raise ValueError(
                    f"Overlay drift: {name}; preserve your changes before reinstalling"
                )
        print("Overlay already applied, unchanged")
        return
    changed = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"], cwd=target, text=True
    )
    if changed:
        raise ValueError("Target has tracked changes; use a clean build copy")
    if any((target / name).exists() for name in BOARDS.values()):
        raise ValueError("Target board directory already exists")
    files = planned_files(target, board)  # Validate every patch anchor before changing any source.
    state = {}
    for name, data in files.items():
        path = target / name
        state[name] = {
            "sha256": digest(data),
            "original": base64.b64encode(path.read_bytes()).decode() if path.exists() else None,
        }
    marker.write_text(json.dumps(state, indent=2) + "\n")
    for name, data in files.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    print(f"Installed {len(files)} overlay files into {target}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--upstream", type=Path, help="Read-only local pinned upstream clone (for --output)"
    )
    parser.add_argument("--output", type=Path, help="New disposable build clone to create")
    parser.add_argument("--target", type=Path, help="Existing clean pinned build clone")
    parser.add_argument("--remove", action="store_true")
    parser.add_argument("--board", choices=BOARDS, default="cores3", help="Board adapter to install; use separate build copies")
    args = parser.parse_args()
    if args.output:
        if args.target or not args.upstream or args.remove:
            parser.error("--output requires --upstream and cannot combine with --target/--remove")
        if args.output.exists():
            parser.error("--output must not exist; use --target to check an installed overlay")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "git",
                "clone",
                "--no-hardlinks",
                str(args.upstream.resolve()),
                str(args.output.resolve()),
            ],
            check=True,
        )
        subprocess.run(["git", "checkout", "--detach", PIN], cwd=args.output, check=True)
        target = args.output
    elif args.target:
        target = args.target
    else:
        parser.error("Specify --output with --upstream, or --target")
    if args.remove:
        remove(target.resolve())
    else:
        apply(target.resolve(), args.board)


if __name__ == "__main__":
    main()
