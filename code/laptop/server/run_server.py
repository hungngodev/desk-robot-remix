"""Run an installed, overlaid Xiaozhi server with this project's private device mapping."""

import argparse
import json
import os
import re
import runpy
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def fleet_device_and_voice_maps(robots: list[dict]) -> tuple[dict, dict]:
    """Bind each native voice to a trusted configured Xiaozhi device."""
    devices = {}
    voices = {}
    for robot in robots:
        if not isinstance(robot, dict):
            raise ValueError("Each fleet robot needs an object config")
        device = robot.get("device_id")
        if not device:
            continue  # Unprovisioned siblings do not own a live voice.
        robot_id = robot.get("id")
        voice = robot.get("voice")
        if (not isinstance(robot_id, str) or not robot_id
                or not isinstance(device, str) or not device.strip()
                or not isinstance(voice, str)
                or re.fullmatch(r"[a-z]{2}_[a-z][a-z0-9_]{0,31}", voice) is None):
            raise ValueError("Provisioned robot needs an ID, device and Kokoro voice")
        if robot_id in devices or device in devices.values():
            raise ValueError("Xiaozhi device and robot identities must be unique")
        devices[robot_id] = device
        voices[robot_id] = voice
    if not devices:
        raise ValueError("Enter at least the first head's Xiaozhi device ID")
    return devices, voices


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
    try:
        mapping, voices = fleet_device_and_voice_maps(config["robots"])
    except (KeyError, TypeError, ValueError) as exc:
        p.error(str(exc))
    os.environ["DESK_ROBOT_DEVICE_MAP"] = json.dumps(mapping)
    os.environ["DESK_ROBOT_NATIVE_VOICE_MAP"] = json.dumps(voices)
    server = ROOT / "laptop/server/build/xiaozhi/main/xiaozhi-server"
    if not (server / "data/.config.yaml").is_file():
        p.error("Create data/.config.yaml using config/xiaozhi.local.example.yaml first")
    import sys

    sys.path.insert(0, str(server))
    os.chdir(server)
    runpy.run_path(str(server / "app.py"), run_name="__main__")


if __name__ == "__main__":
    main()
