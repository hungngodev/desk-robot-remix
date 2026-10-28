"""Create private build settings; does not flash anything or print a token."""

import argparse
import ipaddress
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--robot", choices=["robot-01", "robot-02"], required=True)
    p.add_argument(
        "--server-ip", required=True, help="Mac LAN IPv4 address, reachable from the head"
    )
    args = p.parse_args()
    address = ipaddress.ip_address(args.server_ip)
    if address.version != 4 or address.is_loopback or address.is_unspecified:
        p.error("Use the Mac's reachable LAN IPv4 address")
    env = ROOT / "config/local.env"
    values = dict(
        line.split("=", 1)
        for line in env.read_text().splitlines()
        if line and not line.startswith("#")
    )
    name = "DESK_ROBOT_HEAD_01_TOKEN" if args.robot == "robot-01" else "DESK_ROBOT_HEAD_02_TOKEN"
    token = os.environ.get(name, values.get(name, ""))
    if not re.fullmatch(r"[a-zA-Z0-9_-]{32,128}", token):
        p.error("Generate local credentials first; the head token is missing/invalid")
    board = ROOT / "firmware/head/build/xiaozhi/main/boards/desk-robot/desk-robot-core-s3"
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
        json.dump(config, stream, indent=2)
    print(f"Private build settings prepared for {args.robot}; token hidden. Nothing flashed.")


if __name__ == "__main__":
    main()
