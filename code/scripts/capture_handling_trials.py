"""Capture independent real WROOM MPU6050 samples without commanding actuators.

This read-only operator helper records three deliberately labeled physical
conditions for the existing calibrate_handling.py analyzer. It NEVER enables
motor movement or physical qualification. The operator controls the rig.
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
from desk_robot.handling import raw_mpu6050

LABELS = (("upright", 8), ("tilted", 4), ("shaking", 4))
_ROBOT_ID = re.compile(r"[A-Za-z0-9_-]{1,40}\Z")



def _operator_status_client() -> httpx.AsyncClient:
    """Keep the operator bearer off ambient proxy routes and redirects."""
    return httpx.AsyncClient(trust_env=False, follow_redirects=False)


def _safe_endpoint(url: str, robot: str) -> str:
    if not isinstance(robot, str) or not _ROBOT_ID.fullmatch(robot):
        raise ValueError("Require exact configured robot identity")
    parsed = urlsplit(url)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError("Invalid private Mac API endpoint")
    if parsed.scheme == "http":
        try:
            local = parsed.hostname == "localhost" or ipaddress.ip_address(
                parsed.hostname
            ).is_loopback
        except ValueError:
            local = False
        if not local:
            raise ValueError("Bearer token requires loopback HTTP or HTTPS")
    return url.rstrip("/") + "/v1/robots/" + robot + "/status"


def save_private_trial_rows(output: Path, rows: list[dict]) -> None:
    """Write the full trial to an unchanged directory, not a redirected path."""
    if not rows:
        raise ValueError("No captured IMU samples to write")
    # Serialize before opening any destination: a bad record cannot leave a
    # partial physical calibration file.
    payload = "".join(
        json.dumps(row, separators=(",", ":")) + "\n" for row in rows
    )
    parent = output.parent
    # O_NOFOLLOW on the *file* alone cannot stop an output directory being
    # replaced by a symlink. Bind every write and cleanup to a directory fd.
    original = os.stat(parent, follow_symlinks=False)
    if not stat.S_ISDIR(original.st_mode):
        raise ValueError("Handling trial output parent must not be a symlink")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        directory_flags |= os.O_NOFOLLOW
    directory_fd = os.open(parent, directory_flags)
    created = False
    try:
        held = os.fstat(directory_fd)
        if (held.st_dev, held.st_ino) != (original.st_dev, original.st_ino):
            raise ValueError("Handling trial output parent changed")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(output.name, flags, 0o600, dir_fd=directory_fd)
        created = True
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
        named = os.stat(parent, follow_symlinks=False)
        if (not stat.S_ISDIR(named.st_mode)
                or (named.st_dev, named.st_ino) != (held.st_dev, held.st_ino)):
            raise ValueError("Handling trial output parent changed")
    except BaseException:
        if created:
            # Never unlink via an attacker-retargeted pathname.
            try:
                os.unlink(output.name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
        raise
    finally:
        os.close(directory_fd)


async def capture_phase(
    client: httpx.AsyncClient, *, base_url: str, robot: str,
    token: str, label: str, count: int, sample_interval: float,
    firmware_commit: str, mount_id: str,
    previous_sample: int | None = None, previous_boot: int | None = None,
    previous_receipt: float | None = None,
) -> list[dict]:
    """Accept only newly acquired WROOM status and immobile wheel commands."""
    if label not in {"upright", "tilted", "shaking"} or not 1 <= count <= 100:
        raise ValueError("Invalid physical handling phase")
    if not 0.05 <= sample_interval <= 2:
        raise ValueError("Invalid read-only polling interval")
    if not all(isinstance(x, str) and 1 <= len(x.strip()) <= 128
               for x in (firmware_commit, mount_id)):
        raise ValueError("Require actual firmware and IMU mount identities")
    endpoint = _safe_endpoint(base_url, robot)
    samples: list[dict] = []
    seen, boot, receipt = previous_sample, previous_boot, previous_receipt
    for _ in range(count * 10):
        response = await client.get(
            endpoint,
            headers={"Authorization": f"Bearer {token}"}, timeout=3.0,
        )
        response.raise_for_status()
        observed = time.monotonic()
        body = response.json()
        if not isinstance(body, dict) or body.get("robot_id") != robot:
            raise RuntimeError("Authenticated WROOM status has wrong robot identity")
        if raw_mpu6050(body) is None:
            raise RuntimeError("Robot is moving or MPU6050 evidence is invalid")
        current = body["imu"]["sample_ms"]
        current_boot = body["imu"]["boot_id"]
        if boot is not None and current_boot != boot:
            raise RuntimeError("WROOM reboot during physical IMU trial")
        boot = current_boot
        # The WROOM sample clock is uint32: accept a true rollover, but
        # never treat a delayed pre-wrap conversion as a new sample.
        forward = (current - seen) & 0xffffffff if seen is not None else None
        if forward is None or 0 < forward < 0x80000000:
            if receipt is not None and observed <= receipt:
                raise RuntimeError("Nonmonotonic source receipt")
            samples.append({
                "label": label,
                # This is a HOST RECEIPT timestamp, not a claimed I2C
                # acquisition clock or synchronized head audio timestamp.
                "time_monotonic_s": observed,
                "firmware_commit": firmware_commit,
                "mount_id": mount_id,
                "body": body,
            })
            seen, receipt = current, observed
        if len(samples) == count:
            return samples
        await asyncio.sleep(sample_interval)
    raise RuntimeError("No sufficiently fresh independent MPU6050 conversions")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8008")
    parser.add_argument("--robot", required=True)
    parser.add_argument("--token-env", default="DESK_ROBOT_API_TOKEN")
    parser.add_argument("--firmware-commit", required=True)
    parser.add_argument("--mount-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--interval", type=float, default=0.18)
    args = parser.parse_args()
    _safe_endpoint(args.url, args.robot)
    token = os.getenv(args.token_env, "")
    if len(token) < 24:
        raise ValueError("Operator bearer token not configured")
    if args.output.exists() or args.output.is_symlink():
        raise FileExistsError("Do not overwrite prior measured IMU evidence")
    rows: list[dict] = []
    async with _operator_status_client() as client:
        for label, count in LABELS:
            input(
                f"Physically establish the {label} condition with wheels stopped. "
                "Press Enter to sample read-only IMU status. "
            )
            phase = await capture_phase(
                client, base_url=args.url, robot=args.robot, token=token,
                label=label, count=count, sample_interval=args.interval,
                firmware_commit=args.firmware_commit, mount_id=args.mount_id,
                previous_sample=(rows[-1]["body"]["imu"]["sample_ms"]
                                 if rows else None),
                previous_boot=(rows[-1]["body"]["imu"]["boot_id"]
                               if rows else None),
                previous_receipt=(rows[-1]["time_monotonic_s"]
                                  if rows else None),
            )
            rows.extend(phase)
    # Only write the whole capture after all physically labeled phases
    # complete. The separate analyzer still rejects overlapping classes.
    save_private_trial_rows(args.output, rows)
    print(f"Recorded {len(rows)} distinct samples to {args.output}")
    print("Next run calibrate_handling.py; no physical certificate was issued")


if __name__ == "__main__":
    asyncio.run(main())
