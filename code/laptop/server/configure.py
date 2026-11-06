"""Write a private local-only provider configuration without printing credentials."""

import argparse
import ipaddress
import os
import secrets
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--server-ip", required=True)
    args = p.parse_args()
    address = ipaddress.ip_address(args.server_ip)
    if address.version != 4 or address.is_loopback or address.is_unspecified:
        p.error("Use the Mac's reachable LAN IPv4 address")
    data = yaml.safe_load((ROOT / "config/xiaozhi.local.example.yaml").read_text())
    data["server"]["websocket"] = f"ws://{address}:8000/xiaozhi/v1/"
    data["server"]["auth_key"] = secrets.token_urlsafe(32)
    target = ROOT / "laptop/server/build/xiaozhi/main/xiaozhi-server/data/.config.yaml"
    if not target.parent.parent.is_dir():
        p.error("Install the server overlay first")
    target.parent.mkdir(exist_ok=True)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        yaml.safe_dump(data, stream, sort_keys=False)
    print(f"Private local provider settings created at {target}; credential hidden")


if __name__ == "__main__":
    main()
