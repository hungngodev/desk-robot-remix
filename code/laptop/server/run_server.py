"""Run an installed, overlaid Xiaozhi server with this project's private device mapping."""

import argparse
import json
import os
import re
import runpy
import sys
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

# Standalone launcher uses Xiaozhi's interpreter, not the Mac package venv.
sys.path.insert(0, str(ROOT / "laptop/src"))
from desk_robot.private_files import read_private_env, read_private_text  # noqa: E402


def fleet_device_and_voice_maps(robots: list[dict]) -> tuple[dict[str, str], dict[str, str]]:
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
        if voice in voices.values():
            raise ValueError("Provisioned Xiaozhi fleet voices must be distinct")
        devices[robot_id] = device
        voices[robot_id] = voice
    if not devices:
        raise ValueError("Enter at least the first head's Xiaozhi device ID")
    return devices, voices


def verified_xiaozhi_auth_config(path: Path) -> None:
    """Refuse native pet identity if upstream could bypass device token auth.

    Pinned Xiaozhi WebSocketServer._handle_auth accepts unsigned device IDs
    when auth.enabled is false or the ID is whitelisted. The Mac voice and
    private MCP mapping assumes that device IDs were token authenticated.
    Check the effective local config before any server or pet is registered.
    """
    try:
        config = yaml.safe_load(read_private_text(path))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise ValueError("Cannot verify private Xiaozhi authentication config") from None
    if not isinstance(config, dict) or config.get("read_config_from_api") is not False:
        raise ValueError("Fleet Xiaozhi must use verified local server config")
    server = config.get("server")
    if not isinstance(server, dict):
        raise ValueError("Private Xiaozhi server settings missing")
    auth = server.get("auth")
    if not isinstance(auth, dict) or auth.get("enabled") is not True:
        raise ValueError("Fleet Xiaozhi requires device token authentication")
    # The upstream whitelist deliberately bypasses token checks even when
    # auth.enabled is true. It cannot authorize a private fleet head.
    if auth.get("allowed_devices") != []:
        raise ValueError("Fleet Xiaozhi must disable device auth whitelist")
    key = server.get("auth_key")
    if (not isinstance(key, str) or len(key.strip()) < 32
            or key == "LOCAL_RANDOM_SECRET"):
        raise ValueError("Set a private non-placeholder Xiaozhi auth_key")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, default=ROOT / "config/local.toml")
    args = p.parse_args()
    try:
        with args.config.open("rb") as source:
            config = tomllib.load(source)
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        p.error("Cannot read fleet configuration; check the path and UTF-8 TOML syntax")
    try:
        credentials = read_private_env(ROOT / "config/local.env")
        mapping, voices = fleet_device_and_voice_maps(config["robots"])
    except (OSError, KeyError, TypeError, ValueError) as exc:
        p.error(str(exc))
    for key, value in credentials.items():
        os.environ.setdefault(key, value)
    os.environ["DESK_ROBOT_DEVICE_MAP"] = json.dumps(mapping)
    os.environ["DESK_ROBOT_NATIVE_VOICE_MAP"] = json.dumps(voices)
    server = ROOT / "laptop/server/build/xiaozhi/main/xiaozhi-server"
    local_config = server / "data/.config.yaml"
    if not local_config.is_file():
        p.error("Create data/.config.yaml using config/xiaozhi.local.example.yaml first")
    try:
        verified_xiaozhi_auth_config(local_config)
        from install_overlay import verify_installed_overlay

        verify_installed_overlay(
            ROOT / "upstream/xiaozhi-esp32-server", server.parent.parent,
        )
    except ValueError as exc:
        p.error(str(exc))
    sys.path.insert(0, str(server))
    os.chdir(server)
    runpy.run_path(str(server / "app.py"), run_name="__main__")


if __name__ == "__main__":
    main()
