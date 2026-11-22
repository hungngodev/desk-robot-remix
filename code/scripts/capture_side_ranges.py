"""Read only capture of fresh, real WROOM left/right/rear ToF conversions.

The operator disarms and physically positions the robot for six near/far
phases. Only private authenticated Mac status GET requests are made. Recorded
values feed calibrate_side_ranges.py, never motor or charging authorization.
"""
from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import os
import re
import stat
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

SIDES = {"left": 0, "right": 1, "rear": 2}
PHASES = tuple((side, label) for side in SIDES for label in ("near", "far"))
_ROBOT = re.compile(r"[A-Za-z0-9_-]{1,40}\Z")


def _status_url(base_url: str, robot: str) -> str:
    """Preserve the private operator endpoint rules of capture_handling_trials."""
    if type(robot) is not str or not _ROBOT.fullmatch(robot):
        raise ValueError("Configured robot identity required")
    parsed = urlsplit(base_url)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError("Invalid private Mac endpoint")
    if parsed.scheme == "http":
        try:
            local = parsed.hostname == "localhost" or ipaddress.ip_address(
                parsed.hostname
            ).is_loopback
        except ValueError:
            local = False
        if not local:
            raise ValueError("Bearer token requires loopback HTTP or HTTPS")
    return base_url.rstrip("/") + "/v1/robots/" + robot + "/status"


def _reading(body: object, robot: str, side: str, elapsed_ms: float):
    """Validate a stopped WROOM and the selected, actually new side lens."""
    if not isinstance(body, dict) or body.get("robot_id") != robot:
        raise RuntimeError("Wrong WROOM robot identity")
    motor = body.get("motor")
    if (body.get("armed") is not False or not isinstance(motor, dict)
            or type(motor.get("m0")) is not int or motor["m0"] != 0
            or type(motor.get("m1")) is not int or motor["m1"] != 0
            or type(body.get("drive_ms")) is not int or body["drive_ms"] != 0):
        raise RuntimeError("Disarm wheels and stop every drive request")
    data = body.get("side_ranges")
    if not isinstance(data, dict):
        raise RuntimeError("Actual WROOM side_ranges data required")
    channel = SIDES[side]
    mm, age, stamps = data.get("mm"), data.get("age_ms"), data.get("sample_ms")
    present, valid, boot = (
        data.get("present_mask"), data.get("valid_mask"), data.get("boot_id")
    )
    if (not isinstance(mm, list) or len(mm) != 3
            or not isinstance(age, list) or len(age) != 3
            or not isinstance(stamps, list) or len(stamps) != 3
            or type(present) is not int or not 0 <= present <= 7
            or type(valid) is not int or not 0 <= valid <= 7
            or (valid & ~present) or not valid & (1 << channel)
            or data.get("motion_certified") is not False
            or type(mm[channel]) is not int or not 1 <= mm[channel] <= 1300
            or type(age[channel]) is not int or not 0 <= age[channel] <= 350
            or type(stamps[channel]) is not int
            or not 0 <= stamps[channel] <= 0xffffffff
            or type(boot) is not int or not 1 <= boot <= 0xffffffff
            or not 0 <= elapsed_ms <= 350
            or age[channel] + elapsed_ms > 350):
        raise RuntimeError("Invalid, absent or stale physical side range")
    return data, stamps[channel], boot


async def capture_phase(
    client: httpx.AsyncClient, *, base_url: str, robot: str, token: str,
    side: str, label: str, count: int, interval: float,
    firmware_commit: str, mount_id: str, sample_id_start: int,
    previous_ms: int | None = None, previous_boot: int | None = None,
) -> list[dict]:
    if (side not in SIDES or label not in {"near", "far"}
            or type(count) is not int or not 1 <= count <= 100
            or type(interval) not in (int, float) or not .05 <= interval <= 2
            or type(sample_id_start) is not int or sample_id_start < 1
            or type(token) is not str or len(token) < 24 or not token.isascii()
            or any(type(x) is not str or not 1 <= len(x.strip()) <= 128
                   for x in (firmware_commit, mount_id))):
        raise ValueError("Authenticated, labeled physical ToF capture required")
    endpoint = _status_url(base_url, robot)
    samples = []
    last_ms, boot = previous_ms, previous_boot
    for _ in range(count * 10):
        start = time.monotonic()
        response = await client.get(
            endpoint, headers={"Authorization": f"Bearer {token}"}, timeout=3.0,
        )
        response.raise_for_status()
        received = time.monotonic()
        raw, sample_ms, next_boot = _reading(
            response.json(), robot, side, (received - start) * 1000,
        )
        if boot is not None and next_boot != boot:
            raise RuntimeError("WROOM reboot during side range calibration")
        boot = next_boot
        advance = ((sample_ms - last_ms) & 0xffffffff
                   if last_ms is not None else None)
        if advance is not None and advance >= 0x80000000:
            raise RuntimeError("Replayed or reversed WROOM ToF conversion")
        if advance is None or advance > 0:
            samples.append({
                "robot_id": robot, "direction": side, "label": label,
                "sample_id": sample_id_start + len(samples),
                "side_ranges": raw, "captured_at_monotonic_s": received,
                "firmware_commit": firmware_commit, "mount_id": mount_id,
            })
            last_ms = sample_ms
        if len(samples) == count:
            return samples
        await asyncio.sleep(interval)
    raise RuntimeError("Not enough distinct physical side range conversions")


def _private_output_directory(path: Path) -> int:
    """Open a private directory through checked handles, never path aliases.

    The output's existing parent must be private mode 0700. Stable root-owned
    aliases (such as macOS /var) are allowed only beneath root-owned,
    non-writable ancestors. No folders are created before this inspection.
    """
    absolute = path.absolute()
    if ".." in absolute.parts or absolute.name in ("", ".", ".."):
        raise ValueError("Unsafe physical side-range output traversal")
    descriptor = os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for name in absolute.parent.parts[1:]:
            parent = os.fstat(descriptor)
            entry = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            alias = stat.S_ISLNK(entry.st_mode)
            if alias and (
                entry.st_uid != 0 or parent.st_uid != 0
                or stat.S_IMODE(parent.st_mode) & 0o022
            ):
                raise ValueError("Unsafe side-range output directory symlink")
            flags = os.O_RDONLY | os.O_DIRECTORY
            if not alias:
                flags |= os.O_NOFOLLOW
            next_descriptor = os.open(name, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        if stat.S_IMODE(os.fstat(descriptor).st_mode) & 0o077:
            raise ValueError("Side-range output directory must be private mode 0700")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def preflight_private_output(path: Path) -> tuple[int, int]:
    """Reject unsafe or occupied evidence destinations before physical trials."""
    descriptor = _private_output_directory(path)
    try:
        try:
            os.stat(path.name, dir_fd=descriptor, follow_symlinks=False)
        except FileNotFoundError:
            # Hold this exact identity across awaited operator/HTTP capture.
            # The location must not change while real trials are collected.
            parent = os.fstat(descriptor)
            return parent.st_dev, parent.st_ino
        raise FileExistsError("Never overwrite previous physical side-range evidence")
    finally:
        os.close(descriptor)


def write_private_rows(
    path: Path, rows: list[dict], *, expected_parent: tuple[int, int],
) -> None:
    """Exclusively create real hardware evidence with 0600, even under umask 000."""
    descriptor = _private_output_directory(path)
    try:
        parent = os.fstat(descriptor)
        if (type(expected_parent) is not tuple or len(expected_parent) != 2
                or type(expected_parent[0]) is not int
                or type(expected_parent[1]) is not int
                or (parent.st_dev, parent.st_ino) != expected_parent):
            raise RuntimeError("Private side-range directory changed since preflight")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        with os.fdopen(
            os.open(path.name, flags, 0o600, dir_fd=descriptor),
            "w", encoding="utf-8",
        ) as output:
            for row in rows:
                output.write(json.dumps(row, separators=(",", ":")) + "\n")
    finally:
        os.close(descriptor)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8008")
    parser.add_argument("--robot", required=True)
    parser.add_argument("--token-env", default="DESK_ROBOT_API_TOKEN")
    parser.add_argument("--firmware-commit", required=True)
    parser.add_argument("--mount-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--interval", default=.18, type=float)
    args = parser.parse_args()
    _status_url(args.url, args.robot)
    output_parent = preflight_private_output(args.output)
    token = os.environ.get(args.token_env, "")
    if len(token) < 24 or not token.isascii():
        raise ValueError("Private operator bearer not configured")
    rows = []
    last_side: dict[str, int] = {}
    boot = None
    async with httpx.AsyncClient(follow_redirects=False) as client:
        for side, label in PHASES:
            input(
                f"Disarm tracks. Hold a real {label} target beside the "
                f"{side} lens. Press Enter for 20 new conversions. "
            )
            phase = await capture_phase(
                client, base_url=args.url, robot=args.robot, token=token,
                side=side, label=label, count=20, interval=args.interval,
                sample_id_start=len(rows) + 1,
                firmware_commit=args.firmware_commit, mount_id=args.mount_id,
                previous_ms=last_side.get(side), previous_boot=boot,
            )
            rows.extend(phase)
            last = phase[-1]["side_ranges"]
            boot = last["boot_id"]
            last_side[side] = last["sample_ms"][SIDES[side]]
    write_private_rows(args.output, rows, expected_parent=output_parent)
    print(f"Captured {len(rows)} read only WROOM samples")
    print(
        f"Analyze with: python scripts/calibrate_side_ranges.py "
        f"--robot {args.robot} --input {args.output}"
    )
    print("Physical acceptance and motor/charger authorization remain disabled")


if __name__ == "__main__":
    asyncio.run(main())
