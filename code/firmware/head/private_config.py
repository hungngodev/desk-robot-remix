"""Create private build settings; does not flash anything or print a token."""

import argparse
import ipaddress
import json
import os
import re
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def robot_token_env(config_path, robot_id):
    """Resolve the selected head's credential name from the same fleet as the Mac."""
    robots = tomllib.loads(Path(config_path).read_text()).get("robots", [])
    matches = [robot for robot in robots if robot.get("id") == robot_id]
    if len(matches) != 1 or not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", robot_id):
        raise ValueError("Choose one robot ID from the selected fleet configuration")
    name = matches[0].get("token_env", "")
    if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", name):
        raise ValueError("The selected head needs a valid credential environment name")
    if sum(robot.get("token_env") == name for robot in robots) != 1:
        raise ValueError("Each head needs its own credential environment name")
    return name


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
    values = dict(
        line.split("=", 1)
        for line in (args.secrets.read_text().splitlines() if args.secrets.exists() else [])
        if line and not line.startswith("#") and "=" in line
    )
    token = os.environ.get(name, values.get(name, ""))
    if not re.fullmatch(r"[a-zA-Z0-9_-]{32,128}", token):
        p.error("Generate local credentials first; the head token is missing/invalid")
    build, variant = {
        "cores3": ("xiaozhi", "desk-robot-core-s3"),
        "modular": ("xiaozhi-modular", "desk-robot-modular-s3"),
        "sense": ("xiaozhi-sense", "desk-robot-sense-s3"),
        "waveshare": ("xiaozhi-waveshare", "desk-robot-waveshare-s3-cam"),
    }[args.board]
    board = ROOT / "firmware/head/build" / build / "main/boards/desk-robot" / variant
    config = json.loads((board / "config.json").read_text())
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
    target = board / "config.private.json"
    if target.is_symlink():
        p.error("Refuse a symlinked private build settings target")
    # A failed write must preserve the previous usable settings. Never open
    # the destination with O_TRUNC: that would follow a planted symlink and
    # could leak a real device bearer into an unrelated tracked file.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=board,
            prefix=".config.private.", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            os.fchmod(stream.fileno(), 0o600)
            json.dump(config, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        if target.is_symlink():
            p.error("Private build settings target became a symlink")
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(f"Private build settings prepared for {args.robot}; token hidden. Nothing flashed.")


if __name__ == "__main__":
    main()
