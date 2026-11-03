"""Create private build settings; does not flash anything or print a token."""

import argparse
import ipaddress
import json
import os
import re
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
    p.add_argument("--board", choices=["cores3", "modular", "sense"], default="cores3")
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
    target = board / "config.private.json"
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(config, stream, indent=2)
    print(f"Private build settings prepared for {args.robot}; token hidden. Nothing flashed.")


if __name__ == "__main__":
    main()
