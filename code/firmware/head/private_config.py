"""Create private build settings; does not flash anything or print a token."""

import argparse
import ipaddress
import json
import os
import re
import secrets
import stat
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Provisioning runs in the head toolchain, without Mac package dependencies.
sys.path.insert(0, str(ROOT / "laptop/src"))
from desk_robot.private_files import read_private_env  # noqa: E402


def robot_token_env(config_path, robot_id):
    """Resolve the selected head's credential name from the same fleet as the Mac."""
    robots = tomllib.loads(Path(config_path).read_text()).get("robots", [])
    if not isinstance(robots, list) or any(not isinstance(robot, dict) for robot in robots):
        raise ValueError("Invalid fleet robot configuration")
    matches = [robot for robot in robots if robot.get("id") == robot_id]
    if len(matches) != 1 or not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", robot_id):
        raise ValueError("Choose one robot ID from the selected fleet configuration")
    name = matches[0].get("token_env", "")
    if not isinstance(name, str) or not re.fullmatch(r"[A-Z_][A-Z0-9_]*", name):
        raise ValueError("The selected head needs a valid credential environment name")
    if sum(robot.get("token_env") == name for robot in robots) != 1:
        raise ValueError("Each head needs its own credential environment name")
    return name


def open_board_directory(root, relative):
    """Open every component without following links; retain the final directory identity."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory = os.open(root, flags)
    try:
        for part in relative.parts:
            child = os.open(part, flags, dir_fd=directory)
            os.close(directory)
            directory = child
        return directory
    except BaseException:
        os.close(directory)
        raise


def require_same_directory(root, relative, directory, parser):
    """Reject a renamed or replaced path before publishing private settings."""
    try:
        current = open_board_directory(root, relative)
    except OSError:
        parser.error("Private build directory changed or is inaccessible")
    try:
        if not os.path.samestat(os.fstat(current), os.fstat(directory)):
            parser.error("Private build directory changed")
    finally:
        os.close(current)


def read_template(directory, parser):
    try:
        descriptor = os.open("config.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=directory)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ValueError("Not a regular template")
            with os.fdopen(descriptor, encoding="utf-8", closefd=False) as stream:
                config = json.load(stream)
            builds = config.get("builds") if isinstance(config, dict) else None
            if (not isinstance(builds, list) or len(builds) != 1
                    or not isinstance(builds[0], dict)):
                raise ValueError("Expected exactly one private board build")
            settings = builds[0].get("sdkconfig_append")
            if not isinstance(settings, list) or any(
                not isinstance(item, str) for item in settings
            ):
                raise ValueError("Invalid SDK configuration entries")
            return config
        finally:
            os.close(descriptor)
    except (OSError, ValueError):
        parser.error("Private build template is missing or invalid")


def require_regular_target(directory, parser):
    try:
        mode = os.stat("config.private.json", dir_fd=directory, follow_symlinks=False).st_mode
    except FileNotFoundError:
        return
    if not stat.S_ISREG(mode):
        parser.error("Refuse a nonregular private build settings target")


def write_private_settings(root, relative, directory, config, parser):
    require_same_directory(root, relative, directory, parser)
    require_regular_target(directory, parser)
    # All IO stays relative to the held directory descriptor, including cleanup.
    # A path swap between validation and replace cannot redirect the bearer.
    temporary = f".config.private.{secrets.token_hex(16)}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=directory)
    try:
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", closefd=False) as stream:
                os.fchmod(stream.fileno(), 0o600)
                json.dump(config, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            os.close(descriptor)
        require_same_directory(root, relative, directory, parser)
        require_regular_target(directory, parser)
        os.replace(temporary, "config.private.json", src_dir_fd=directory, dst_dir_fd=directory)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--robot", required=True)
    p.add_argument("--config", type=Path, default=ROOT / "config/fleet.example.toml")
    p.add_argument("--secrets", type=Path, default=ROOT / "config/local.env")
    p.add_argument("--board", choices=["cores3", "modular", "sense", "waveshare"], default="cores3")
    p.add_argument("--aec-delay-ms", type=int, default=90,
                   help="Sense-only measured acoustic reference alignment (0..250ms)")
    p.add_argument("--continuous-audio", action="store_true",
                   help="Explicit opt in to Sense realtime microphone after boot; BOOT stops it")
    p.add_argument("--bench-aec-capture", action="store_true",
                   help="Private Sense-only one-shot raw PCM calibration, never production")
    p.add_argument(
        "--server-ip", required=True, help="Mac LAN IPv4 address, reachable from the head"
    )
    args = p.parse_args()
    try:
        address = ipaddress.ip_address(args.server_ip)
        name = robot_token_env(args.config, args.robot)
    except (OSError, ValueError) as error:
        p.error(str(error))
    if address.version != 4 or address.is_loopback or address.is_unspecified:
        p.error("Use the Mac's reachable LAN IPv4 address")
    if not 0 <= args.aec_delay_ms <= 250:
        p.error("Sense AEC delay must be within 0..250 ms")
    if args.board != "sense" and args.aec_delay_ms != 90:
        p.error("Custom AEC reference delay is for the Sense board only")
    if args.continuous_audio and args.board != "sense":
        p.error("Continuous real-time microphone is qualified only for the Sense audio path")
    if args.bench_aec_capture and (
        args.board != "sense" or not args.continuous_audio or args.aec_delay_ms != 0
    ):
        p.error("Private PCM calibration requires Sense, continuous mic consent and zero AEC delay")
    try:
        values = read_private_env(args.secrets)
    except (OSError, ValueError) as error:
        p.error(str(error))
    token = os.environ.get(name, values.get(name, ""))
    if not re.fullmatch(r"[a-zA-Z0-9_-]{32,128}", token):
        p.error("Generate local credentials first; the head token is missing/invalid")
    build, variant = {
        "cores3": ("xiaozhi", "desk-robot-core-s3"),
        "modular": ("xiaozhi-modular", "desk-robot-modular-s3"),
        "sense": ("xiaozhi-sense", "desk-robot-sense-s3"),
        "waveshare": ("xiaozhi-waveshare", "desk-robot-waveshare-s3-cam"),
    }[args.board]
    root = ROOT.resolve()
    relative = Path("firmware/head/build") / build / "main/boards/desk-robot" / variant
    try:
        directory = open_board_directory(root, relative)
    except OSError:
        p.error("Private build directory is missing, symlinked or inaccessible")
    try:
        config = read_template(directory, p)
        config["builds"][0]["sdkconfig_append"] = [
            x
            for x in config["builds"][0]["sdkconfig_append"]
            if not x.startswith(
                ("CONFIG_DESK_ROBOT_ID=", "CONFIG_DESK_ROBOT_TOKEN=", "CONFIG_OTA_URL=")
            )
        ]
        config["builds"][0]["sdkconfig_append"] += [
            f'CONFIG_DESK_ROBOT_ID="{args.robot}"',
            f'CONFIG_DESK_ROBOT_TOKEN="{token}"',
            f'CONFIG_OTA_URL="http://{address}:8003/xiaozhi/ota/"',
        ]
        if args.board == "sense":
            config["builds"][0]["sdkconfig_append"] = [
                item for item in config["builds"][0]["sdkconfig_append"]
                if not item.startswith((
                    "CONFIG_DESK_ROBOT_AEC_DELAY_MS=",
                    "CONFIG_DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED=",
                    "CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED=",
                ))
            ]
            config["builds"][0]["sdkconfig_append"].extend([
                f"CONFIG_DESK_ROBOT_AEC_DELAY_MS={args.aec_delay_ms}",
                "CONFIG_DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED="
                + ("y" if args.continuous_audio else "n"),
                "CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED="
                + ("y" if args.bench_aec_capture else "n"),
            ])
        write_private_settings(root, relative, directory, config, p)
    finally:
        os.close(directory)
    print(f"Private build settings prepared for {args.robot}; token hidden. Nothing flashed.")


if __name__ == "__main__":
    main()
