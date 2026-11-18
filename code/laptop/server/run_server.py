"""Run an installed, overlaid Xiaozhi server with this project's private device mapping."""

import argparse
import json
import os
import runpy
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, default=ROOT / "config/local.toml")
    args = p.parse_args()
    with args.config.open("rb") as source:
        config = tomllib.load(source)
    for line in (ROOT / "config/local.env").read_text().splitlines():
        if line and not line.startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key, value)
    mapping = {r["id"]: r["device_id"] for r in config["robots"] if r.get("device_id")}
    if not mapping:
        p.error("Enter at least the first head's Xiaozhi device ID in local.toml")
    os.environ["DESK_ROBOT_DEVICE_MAP"] = json.dumps(mapping)
    server = ROOT / "laptop/server/build/xiaozhi/main/xiaozhi-server"
    if not (server / "data/.config.yaml").is_file():
        p.error("Create data/.config.yaml using config/xiaozhi.local.example.yaml first")
    import sys

    sys.path.insert(0, str(server))
    os.chdir(server)
    runpy.run_path(str(server / "app.py"), run_name="__main__")


if __name__ == "__main__":
    main()
