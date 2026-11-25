"""Read-only Sense physical BOOT microphone trial, using no recorded PCM.

Begin with a consented Xiaozhi microphone session. After the script sees
live input, press BOOT once and hold mute, then press BOOT again. Mic driver
progress is NOT proof that in-flight network packets were recalled.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import stat
import time
from pathlib import Path

import httpx
from desk_robot.config import load_settings
from desk_robot.transport import HttpHead

ROOT = Path(__file__).resolve().parents[1]


def _private_report_directory_fd(parent: Path) -> int:
    """Hold the verified private directory throughout report creation."""
    # Refuse lexical parent traversal before the filesystem resolves links.
    # os.path.abspath would erase an alias/.. sequence prematurely.
    absolute = parent.absolute()
    if ".." in absolute.parts:
        raise ValueError("Unsafe privacy trial report parent traversal")
    descriptor = os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for name in absolute.parts[1:]:
            owner = os.fstat(descriptor)
            try:
                entry = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            except FileNotFoundError:
                # Missing children may only be created beneath a previously
                # verified directory handle, never through an unchecked alias.
                os.mkdir(name, mode=0o700, dir_fd=descriptor)
                entry = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            # macOS /var is a stable root-owned alias only under an
            # equally root-owned and non-writable parent directory.
            if stat.S_ISLNK(entry.st_mode) and (
                entry.st_uid != 0 or owner.st_uid != 0
                or stat.S_IMODE(owner.st_mode) & 0o022
            ):
                raise ValueError("Privacy trial report directory has unsafe symlink")
            flags = os.O_RDONLY | os.O_DIRECTORY
            if not stat.S_ISLNK(entry.st_mode):
                flags |= os.O_NOFOLLOW
            next_descriptor = os.open(name, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        if stat.S_IMODE(os.fstat(descriptor).st_mode) & 0o077:
            raise ValueError("Privacy trial report directory must be private mode 0700")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def preflight_private_report(path: Path) -> None:
    """Fail before physical BOOT trials if the measurement cannot be stored."""
    if path.parent.is_symlink():
        raise ValueError("Privacy trial report directory must be private mode 0700")
    descriptor = _private_report_directory_fd(path.parent)
    os.close(descriptor)
    if path.exists() or path.is_symlink():
        raise FileExistsError("Privacy trial report already exists")


def save_private_report(path: Path, report: dict) -> None:
    preflight_private_report(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    descriptor = _private_report_directory_fd(path.parent)
    try:
        with os.fdopen(
            os.open(path.name, flags, 0o600, dir_fd=descriptor),
            "w", encoding="utf-8",
        ) as output:
            json.dump(report, output, indent=2)
            output.write("\n")
    finally:
        os.close(descriptor)


def _valid(sample: dict, robot_id: str) -> bool:
    return (
        type(sample) is dict
        and sample.get("robot_id") == robot_id
        and type(sample.get("boot")) is int
        and 0 <= sample["boot"] <= 0xffffffff
        and type(sample.get("microphone_frames_read")) is int
        and 0 <= sample["microphone_frames_read"] <= 0xffffffff
        and type(sample.get("microphone_privacy_muted")) is bool
        and type(sample.get("microphone_privacy_epoch")) is int
        and 0 <= sample["microphone_privacy_epoch"] <= 0xffffffff
        and sample.get("speaker_playback_verified") is False
        and sample.get("aec_physically_qualified") is False
    )


async def measure(head, robot_id: str, *, seconds: float = 15,
                  poll_period_s: float = 0.1, hold_min_s: float = 0.8,
                  quiet_grace_s: float = 0.2,
                  clock=time.monotonic, sleeper=asyncio.sleep,
                  on_ready=None) -> dict:
    """Read the real authenticated codec while a human toggles BOOT twice."""
    values = (seconds, poll_period_s, hold_min_s, quiet_grace_s)
    if (any(type(v) not in (int, float) or not math.isfinite(v)
            for v in values)
            or not 0.1 <= seconds <= 600
            or not 0.05 <= poll_period_s <= 2
            or not 0.1 <= hold_min_s <= 10
            or not 0 <= quiet_grace_s < hold_min_s
            or not isinstance(robot_id, str) or not robot_id):
        raise ValueError("Invalid Sense physical privacy trial limits")
    started = clock()
    deadline = started + seconds
    first = previous = None
    phase = "initial_unmuted"
    muted_at = quiet_base = unmute_base = None
    quiet_samples = 0
    late_reads = resumed = False
    errors: list[str] = []
    accepted = 0
    while clock() < deadline and phase != "complete":
        try:
            remaining = deadline - clock()
            sample = await asyncio.wait_for(
                head.audio_reference_status(),
                timeout=min(1.0, max(0.05, remaining)),
            )
            if not _valid(sample, robot_id):
                raise ValueError("Untrusted Sense privacy receipt")
            if previous is not None:
                if sample["boot"] != previous["boot"]:
                    errors.append("Head reboot during trial")
                    break
                if (sample["microphone_frames_read"] < previous["microphone_frames_read"]
                        or sample["microphone_privacy_epoch"] <
                        previous["microphone_privacy_epoch"]):
                    errors.append("Mic read or BOOT counter rolled backward")
                    break
                # A skipped epoch can hide an entire mute/unmute cycle between
                # polls. Only one observed transition may advance the epoch.
                expected_epoch = previous["microphone_privacy_epoch"] + int(
                    sample["microphone_privacy_muted"] != previous["microphone_privacy_muted"]
                )
                if sample["microphone_privacy_epoch"] != expected_epoch:
                    errors.append("Unobserved or inconsistent BOOT privacy transition")
                    break
            now = clock()
            accepted += 1
            if first is None:
                first = sample
                if sample["microphone_privacy_muted"]:
                    errors.append("Begin unmuted with explicit operator consent")
                    break
            elif phase == "initial_unmuted":
                if sample["microphone_privacy_muted"]:
                    errors.append("No active input baseline before first BOOT")
                    break
                if sample["microphone_frames_read"] > first["microphone_frames_read"]:
                    phase = "await_mute"
                    if on_ready is not None:
                        on_ready("Press physical BOOT to mute. Hold for at least 1 second.")
            elif phase == "await_mute":
                if sample["microphone_privacy_muted"]:
                    if sample["microphone_privacy_epoch"] <= first["microphone_privacy_epoch"]:
                        errors.append("Mute without new BOOT epoch")
                        break
                    muted_at = now
                    phase = "hold_muted"
            elif phase == "hold_muted":
                if sample["microphone_privacy_muted"]:
                    if now - muted_at >= quiet_grace_s:
                        if quiet_base is None:
                            quiet_base = sample["microphone_frames_read"]
                        elif sample["microphone_frames_read"] != quiet_base:
                            late_reads = True
                        quiet_samples += 1
                    if (now - muted_at >= hold_min_s and quiet_samples >= 2
                            and on_ready is not None):
                        on_ready("Press physical BOOT again to unmute.")
                        on_ready = None
                else:
                    if now - muted_at < hold_min_s or quiet_samples < 2:
                        errors.append("Muted interval was too short")
                        break
                    if sample["microphone_privacy_epoch"] < first["microphone_privacy_epoch"] + 2:
                        errors.append("Unmute without second BOOT epoch")
                        break
                    unmute_base = sample["microphone_frames_read"]
                    phase = "await_resume"
            elif phase == "await_resume":
                if sample["microphone_privacy_muted"]:
                    errors.append("Extra BOOT interruption")
                    break
                if sample["microphone_frames_read"] > unmute_base:
                    resumed = True
                    phase = "complete"
            previous = sample
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if len(errors) < 12:
                errors.append(type(exc).__name__ + ": " + str(exc)[:100])
        await sleeper(min(poll_period_s, max(0, deadline - clock())))
    return {
        "robot_id": robot_id,
        "head_boot": first["boot"] if first else None,
        "polls_accepted": accepted,
        "elapsed_s": round(clock() - started, 3),
        "last_phase": phase,
        "muted_samples_after_grace": quiet_samples,
        "microphone_counter_stable_while_muted": quiet_samples >= 2 and not late_reads,
        "post_unmute_microphone_reads_resumed": resumed,
        "errors": errors,
        "software_boot_privacy_cycle_observed": (
            phase == "complete" and accepted >= 5 and not errors
            and quiet_samples >= 2 and not late_reads and resumed
        ),
        "raw_pcm_captured": False,
        "actual_network_audio_cutoff_verified": False,
        "physical_audio_privacy_qualified": False,
        "speaker_playback_verified": False,
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config/local.toml")
    parser.add_argument("--robot", required=True)
    parser.add_argument("--seconds", type=float, default=15)
    parser.add_argument("--poll-period", type=float, default=0.1)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    settings = load_settings(args.config)
    if settings.mode != "hardware":
        parser.error("Use real hardware, not simulation")
    robot = settings.robot(args.robot)
    if not robot.device_id:
        parser.error("A unique actual Xiaozhi device identity is required")
    preflight_private_report(args.report)
    print("Start consented live Xiaozhi listening. Hold the BOOT button ready.", flush=True)
    async with httpx.AsyncClient(trust_env=False) as client:
        report = await measure(
            HttpHead(robot, client), robot.id, seconds=args.seconds,
            poll_period_s=args.poll_period, on_ready=lambda m: print(m, flush=True),
        )
    save_private_report(args.report, report)
    print(json.dumps(report, indent=2))
    return 0 if report["software_boot_privacy_cycle_observed"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
