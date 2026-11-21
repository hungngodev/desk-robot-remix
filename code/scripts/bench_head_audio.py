"""Read only time series of real Sense AEC reference integrity counters.

Uses the existing authenticated Xiaozhi head and does not record, stream,
save or expose microphone PCM. A good software reference does not prove echo
cancellation, audible playback or physical human barge-in timing.
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
def preflight_private_report(path: Path) -> None:
    """Refuse to record a benchmark against an existing or public report."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if (path.parent.is_symlink()
            or stat.S_IMODE(path.parent.stat().st_mode) & 0o077):
        raise ValueError("Audio bench report directory must be private mode 0700")
    if path.exists() or path.is_symlink():
        raise FileExistsError("Audio bench report already exists")


def save_private_report(path: Path, report: dict) -> None:
    preflight_private_report(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    with os.fdopen(os.open(path, flags, 0o600), "w", encoding="utf-8") as out:
        json.dump(report, out, indent=2)
        out.write("\n")


COUNTERS = (
    "reference_underflow_reads",
    "reference_overwrite_reads",
    "discarded_stale_writes",
    "short_output_writes",
    "microphone_frames_read",
    "speaker_frames_accepted",
)


async def measure(head, robot_id: str, *, seconds: float,
                  poll_period_s: float = 0.2) -> dict:
    """Poll the already active codec without altering its audio owner."""
    if (type(seconds) not in (int, float) or not math.isfinite(seconds)
            or not 0.1 <= seconds <= 3600
            or type(poll_period_s) not in (int, float)
            or not math.isfinite(poll_period_s)
            or not 0.05 <= poll_period_s <= 10):
        raise ValueError("Invalid bounded audio bench interval or duration")
    started = time.monotonic()
    deadline = started + seconds
    previous: dict | None = None
    first: dict | None = None
    last: dict | None = None
    errors: list[str] = []
    invalid_receipts = 0
    received = 0
    integrity_failure_seen = False
    privacy_muted_seen = False
    counter_regressions = 0
    while time.monotonic() < deadline:
        try:
            remaining = deadline - time.monotonic()
            sample = await asyncio.wait_for(
                head.audio_reference_status(),
                timeout=min(1.0, max(0.05, remaining)),
            )
            if (not isinstance(sample, dict)
                    or sample.get("robot_id") != robot_id
                    or type(sample.get("boot")) is not int
                    or not 0 <= sample["boot"] <= 0xffffffff
                    or any(type(sample.get(key)) is not int
                           or not 0 <= sample[key] <= 0xffffffff
                           for key in COUNTERS)
                    or type(sample.get("reference_integrity_failed")) is not bool
                    or type(sample.get("microphone_privacy_muted")) is not bool
                    or type(sample.get("microphone_privacy_epoch")) is not int
                    or not 0 <= sample["microphone_privacy_epoch"] <= 0xffffffff
                    or sample.get("speaker_playback_verified") is not False
                    or sample.get("aec_physically_qualified") is not False):
                raise ValueError("Untrusted robot AEC reference receipt")
            if previous is not None and (
                sample["boot"] != previous["boot"]
                or sample["microphone_privacy_epoch"] < previous["microphone_privacy_epoch"]
                or any(sample[key] < previous[key] for key in COUNTERS)
                or (previous["reference_integrity_failed"]
                    and not sample["reference_integrity_failed"])
            ):
                counter_regressions += 1
                raise ValueError("Sense AEC counter reset or identity continuity lost")
            previous = sample
            received += 1
            if first is None:
                first = sample
            last = sample
            integrity_failure_seen |= sample["reference_integrity_failed"]
            privacy_muted_seen |= sample["microphone_privacy_muted"]
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            invalid_receipts += 1
            if len(errors) < 20:
                errors.append(type(exc).__name__ + ": " + str(exc)[:120])
        await asyncio.sleep(min(poll_period_s, max(0, deadline - time.monotonic())))

    deltas = (
        {key: last[key] - first[key] for key in COUNTERS}
        if first is not None and last is not None else None
    )
    return {
        "robot_id": robot_id,
        "head_boot": first["boot"] if first is not None else None,
        "elapsed_s": round(time.monotonic() - started, 3),
        "samples": received,
        "probe_errors": invalid_receipts,
        "probe_error_details": errors,
        "counter_regressions": counter_regressions,
        "reference_counter_delta": deltas,
        "reference_integrity_failure_observed": integrity_failure_seen,
        "microphone_privacy_muted_observed": privacy_muted_seen,
        "microphone_privacy_epoch_delta": (
            last["microphone_privacy_epoch"] - first["microphone_privacy_epoch"]
            if first is not None and last is not None else None
        ),
        "reference_software_integrity_observed": (
            received >= 2 and invalid_receipts == 0
            and not integrity_failure_seen and not privacy_muted_seen
            and deltas is not None
            and deltas["reference_underflow_reads"] == 0
            and deltas["reference_overwrite_reads"] == 0
            and deltas["discarded_stale_writes"] == 0
            and deltas["short_output_writes"] == 0
            and deltas["microphone_frames_read"] > 0
            and deltas["speaker_frames_accepted"] > 0
        ),
        "raw_pcm_captured": False,
        "physical_aec_delay_measured": False,
        "actual_speaker_playback_verified": False,
        "natural_human_barge_in_verified": False,
    }


async def main() -> int:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--config", type=Path, default=ROOT / "config/local.toml")
    cli.add_argument("--robot", required=True)
    cli.add_argument("--seconds", type=float, default=60)
    cli.add_argument("--poll-period", type=float, default=0.2)
    cli.add_argument("--report", type=Path, required=True)
    args = cli.parse_args()
    if not 5 <= args.seconds <= 600 or not 0.05 <= args.poll_period <= 2:
        cli.error("Real audio bench requires 5..600 seconds, 0.05..2s polls")
    settings = load_settings(args.config)
    if settings.mode != "hardware":
        cli.error("Use real hardware settings, not simulation")
    robot = settings.robot(args.robot)
    if not robot.device_id:
        cli.error("Configure the unique Xiaozhi device identity")
    preflight_private_report(args.report)
    async with httpx.AsyncClient() as client:
        head = HttpHead(robot, client)
        report = await measure(
            head, robot.id, seconds=args.seconds,
            poll_period_s=args.poll_period,
        )
    save_private_report(args.report, report)
    print(json.dumps(report, indent=2))
    return 0 if report["reference_software_integrity_observed"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
