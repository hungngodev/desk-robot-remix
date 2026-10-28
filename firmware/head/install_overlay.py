#!/usr/bin/env python3
"""Apply a version-pinned, reversible Xiaozhi board overlay; never changes the source clone."""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

PIN = "c435f99a88066029ec2dbd2d758c8cc9d051565b"
BOARD = "main/boards/desk-robot-core-s3"
MARKER = ".desk-robot-head-overlay.json"
HERE = Path(__file__).resolve().parent


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise ValueError(f"Upstream patch anchor changed: {old[:80]!r}")
    return text.replace(old, new, 1)


def planned_files(target: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    stock = target / "main/boards/m5stack/core-s3"
    for name in ("config.h", "cores3_audio_codec.h", "cores3_audio_codec.cc"):
        files[f"{BOARD}/{name}"] = (stock / name).read_bytes()
    source = (stock / "m5stack_core_s3.cc").read_text()
    source = source.replace("M5StackCoreS3Board", "DeskRobotCoreS3Board")
    source = replace_once(source, '#include "wifi_board.h"', '#include "wifi_board.h"\n#include "robot_bridge.h"')
    source = replace_once(source, "        InitializeFt6336TouchPad();", "        InitializeFt6336TouchPad();\n        // Separate robot identity; stock audio, display and camera initialization remain intact.\n        static desk_robot::Bridge robot_bridge(camera_);\n        robot_bridge.Start();")
    files[f"{BOARD}/desk_robot_core_s3.cc"] = source.encode()
    for path in (HERE / "overlay").iterdir():
        if path.suffix in (".h", ".cc"):
            files[f"{BOARD}/{path.name}"] = path.read_bytes()
    config = json.loads((stock / "config.json").read_text())
    config["manufacturer"] = "desk-robot"
    config["type"] = "desk-robot-core-s3"
    config["builds"][0]["name"] = "desk-robot-core-s3"
    config["builds"][0]["sdkconfig_append"].extend([
        'CONFIG_DESK_ROBOT_ID="robot-01"', 'CONFIG_DESK_ROBOT_TOKEN=""',
    ])
    files[f"{BOARD}/config.json"] = (json.dumps(config, indent=2) + "\n").encode()
    files[f"{BOARD}/README.md"] = (HERE / "BOARD_README.md").read_bytes()

    path = "main/Kconfig.projbuild"
    text = (target / path).read_text()
    text = replace_once(text, "    config BOARD_TYPE_M5STACK_CORE_S3\n", "    config BOARD_TYPE_DESK_ROBOT_CORE_S3\n        bool \"Desk robot CoreS3 Lite\"\n        depends on IDF_TARGET_ESP32S3\n    config BOARD_TYPE_M5STACK_CORE_S3\n")
    text += '''\nmenu "Desk robot private settings"
    depends on BOARD_TYPE_DESK_ROBOT_CORE_S3
config DESK_ROBOT_ID
    string "Unique robot ID"
    default "robot-01"
config DESK_ROBOT_TOKEN
    string "Private LAN bearer token (32..128 characters; empty disables robot bridge)"
    default ""
endmenu
'''
    files[path] = text.encode()
    path = "main/CMakeLists.txt"
    text = (target / path).read_text()
    branch = '''elseif(CONFIG_BOARD_TYPE_DESK_ROBOT_CORE_S3)
    set(BOARD_DIR "desk-robot-core-s3")
    set(BUILTIN_TEXT_FONT font_noto_sans_basic_20_4)
    set(BUILTIN_ICON_FONT font_material_symbols_20_4)
    set(DEFAULT_EMOJI_COLLECTION noto-color-emoji_64)
'''
    text = replace_once(text, "elseif(CONFIG_BOARD_TYPE_M5STACK_CORE_S3)\n", branch + "elseif(CONFIG_BOARD_TYPE_M5STACK_CORE_S3)\n")
    text = replace_once(text, 'set(MAIN_PRIV_REQUIRES_EXTRA "")', 'set(MAIN_PRIV_REQUIRES_EXTRA "")\nif(CONFIG_BOARD_TYPE_DESK_ROBOT_CORE_S3)\n    list(APPEND MAIN_PRIV_REQUIRES_EXTRA esp_http_server)\nendif()')
    files[path] = text.encode()

    path = "main/boards/common/camera.h"
    text = (target / path).read_text()
    text = replace_once(text, "#include <expected>", "#include <expected>\n#include \"sdkconfig.h\"\n#ifdef CONFIG_BOARD_TYPE_DESK_ROBOT_CORE_S3\n#include <mutex>\n#include <vector>\n#endif")
    text = replace_once(text, "    virtual ~Camera() = default;", '''    virtual ~Camera() = default;
#ifdef CONFIG_BOARD_TYPE_DESK_ROBOT_CORE_S3
    // Capture+Explain must hold the same lock as HTTP snapshots across both calls.
    std::recursive_mutex& AccessMutex() { return access_mutex_; }
    virtual std::expected<std::vector<uint8_t>, std::string> SnapshotJpeg() {
        return std::unexpected("Snapshot not supported by this camera");
    }
private:
    std::recursive_mutex access_mutex_;
public:
#endif''')
    files[path] = text.encode()
    path = "main/boards/common/esp_video.h"
    text = (target / path).read_text()
    text = replace_once(text, "    virtual bool Capture();", "    virtual bool Capture();\n#ifdef CONFIG_BOARD_TYPE_DESK_ROBOT_CORE_S3\n    std::expected<std::vector<uint8_t>, std::string> SnapshotJpeg() override;\n#endif")
    files[path] = text.encode()
    path = "main/boards/common/esp_video.cc"
    text = (target / path).read_text()
    for anchor in ("bool EspVideo::Capture() {", "std::expected<std::string, std::string> EspVideo::Explain(const std::string& question) {"):
        text = replace_once(text, anchor, anchor + "\n#ifdef CONFIG_BOARD_TYPE_DESK_ROBOT_CORE_S3\n    std::lock_guard<std::recursive_mutex> camera_lock(AccessMutex());\n#endif")
    text += '''
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
'''
    files[path] = text.encode()
    path = "main/mcp_server.cc"
    text = (target / path).read_text()
    text = replace_once(text, "                    if (!camera->Capture()) {", "#ifdef CONFIG_BOARD_TYPE_DESK_ROBOT_CORE_S3\n                    std::lock_guard<std::recursive_mutex> camera_lock(camera->AccessMutex());\n#endif\n                    if (!camera->Capture()) {")
    files[path] = text.encode()
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
    board = target / BOARD
    if board.is_dir() and not any(board.iterdir()):
        board.rmdir()


def apply(target: Path) -> None:
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=target, text=True).strip()
    if head != PIN:
        raise ValueError(f"Requires Xiaozhi commit {PIN}, found {head}")
    marker = target / MARKER
    if marker.exists():
        state = json.loads(marker.read_text())
        for name, info in state.items():
            path = target / name
            if not path.is_file() or digest(path.read_bytes()) != info["sha256"]:
                raise ValueError(f"Overlay drift: {name}; preserve your changes before reinstalling")
        print("Overlay already applied, unchanged")
        return
    changed = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=target, text=True)
    if changed:
        raise ValueError("Target has tracked changes; use a clean build copy")
    if (target / BOARD).exists():
        raise ValueError("Target board directory already exists")
    files = planned_files(target)  # Validate every patch anchor before changing any source.
    state = {}
    for name, data in files.items():
        path = target / name
        state[name] = {"sha256": digest(data), "original": base64.b64encode(path.read_bytes()).decode() if path.exists() else None}
    marker.write_text(json.dumps(state, indent=2) + "\n")
    for name, data in files.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    print(f"Installed {len(files)} overlay files into {target}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, help="Read-only local pinned upstream clone (for --output)")
    parser.add_argument("--output", type=Path, help="New disposable build clone to create")
    parser.add_argument("--target", type=Path, help="Existing clean pinned build clone")
    parser.add_argument("--remove", action="store_true")
    args = parser.parse_args()
    if args.output:
        if args.target or not args.upstream or args.remove:
            parser.error("--output requires --upstream and cannot combine with --target/--remove")
        if args.output.exists():
            parser.error("--output must not exist; use --target to check an installed overlay")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--no-hardlinks", str(args.upstream.resolve()), str(args.output.resolve())], check=True)
        subprocess.run(["git", "checkout", "--detach", PIN], cwd=args.output, check=True)
        target = args.output
    elif args.target:
        target = args.target
    else:
        parser.error("Specify --output with --upstream, or --target")
    if args.remove:
        remove(target.resolve())
    else:
        apply(target.resolve())

if __name__ == "__main__":
    main()
