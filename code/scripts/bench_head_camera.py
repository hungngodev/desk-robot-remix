"""Read-only live XIAO Sense camera/telemetry bench, no motors or recording.

Run only against a physically connected, authenticated head. The report is
actual HTTP timing, not sensor exposure, AEC, acoustic or charging acceptance.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from pathlib import Path

import httpx

from desk_robot.config import load_settings
from desk_robot.transport import HttpHead

ROOT = Path(__file__).resolve().parents[1]


def summarize(values: list[float]) -> dict:
    if not values:
        return {"count": 0, "p50_ms": None, "p95_ms": None, "max_ms": None}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "p50_ms": round(ordered[(len(ordered) - 1) // 2] * 1000, 1),
        "p95_ms": round(ordered[math.ceil(0.95 * len(ordered)) - 1] * 1000, 1),
        "max_ms": round(ordered[-1] * 1000, 1),
    }


async def measure(
    head, robot_id: str, *, seconds: float,
    camera_period_s: float = 1.0, status_period_s: float = 0.2,
) -> dict:
    """Exercise existing head transport; never send any POST/motion command."""
    if not (0.1 <= seconds <= 3600
            and 0.05 <= camera_period_s <= 10
            and 0.05 <= status_period_s <= 10):
        raise ValueError("Invalid read-only bench duration or periods")
    camera_times: list[float] = []
    status_times: list[float] = []
    camera_sizes: list[int] = []
    camera_errors: list[str] = []
    status_errors: list[str] = []
    camera_error_count = status_error_count = 0
    seen_camera_identities: set[tuple[int, int, int]] = set()
    started = time.monotonic()
    deadline = started + seconds

    async def poll_camera():
        due = started
        while time.monotonic() < deadline:
            begin = time.monotonic()
            try:
                # Never leave an optional camera HTTP request blocking this
                # bounded, read-only acoustic/contention experiment forever.
                jpeg = await asyncio.wait_for(
                    head.snapshot(), timeout=min(4.0, max(0.05, deadline - begin))
                )
                if not isinstance(jpeg, bytes) or not jpeg.startswith(b"\xff\xd8") \
                        or not jpeg.endswith(b"\xff\xd9"):
                    raise ValueError("Head returned truncated or non-JPEG data")
                identity = getattr(head, "_last_camera", None)
                if identity is not None:
                    if identity in seen_camera_identities:
                        raise ValueError("Head returned duplicate camera identity")
                    seen_camera_identities.add(identity)
                camera_sizes.append(len(jpeg))
                camera_times.append(time.monotonic() - begin)
            except Exception as exc:
                camera_error_count += 1
                if len(camera_errors) < 20:
                    camera_errors.append(
                        type(exc).__name__ + ": " + str(exc)[:110]
                    )
            # Skip missed slots rather than burst catching up after a
            # stalled JPEG; audio and body telemetry keep priority.
            due = max(due + camera_period_s, time.monotonic())
            await asyncio.sleep(max(0, min(deadline, due) - time.monotonic()))

    async def poll_status():
        due = started
        while time.monotonic() < deadline:
            begin = time.monotonic()
            try:
                state = await asyncio.wait_for(
                    head.status(), timeout=min(0.8, max(0.05, deadline - begin))
                )
                if not isinstance(state, dict) or state.get("robot_id") != robot_id:
                    raise ValueError("Head status identity invalid")
                status_times.append(time.monotonic() - begin)
            except Exception as exc:
                status_error_count += 1
                if len(status_errors) < 20:
                    status_errors.append(
                        type(exc).__name__ + ": " + str(exc)[:110]
                    )
            due = max(due + status_period_s, time.monotonic())
            await asyncio.sleep(max(0, min(deadline, due) - time.monotonic()))

    await asyncio.gather(poll_camera(), poll_status())
    elapsed = max(0.001, time.monotonic() - started)
    return {
        "robot_id": robot_id,
        "elapsed_s": round(elapsed, 3),
        "requested_camera_fps": round(1.0 / camera_period_s, 3),
        "successful_camera_fps": round(len(camera_times) / elapsed, 3),
        "camera_latency": summarize(camera_times),
        "status_latency": summarize(status_times),
        "largest_jpeg_bytes": max(camera_sizes, default=0),
        "distinct_source_camera_identities": len(seen_camera_identities),
        "camera_errors": camera_errors[:20],
        "camera_error_count": camera_error_count,
        "status_errors": status_errors[:20],
        "status_error_count": status_error_count,
        "camera_transport_probe_only": True,
        "sensor_exposure_clock_synchronized": False,
        "physical_aec_latency_measured": False,
        "speaker_silence_verified": False,
        "charging_verified": False,
        "assembly_ready": False,
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config/local.toml")
    parser.add_argument("--robot", required=True)
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--camera-period", type=float, default=1.0)
    parser.add_argument("--status-period", type=float, default=0.2)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if not 5 <= args.seconds <= 300:
        parser.error("Physical camera bench requires 5..300 seconds")
    settings = load_settings(args.config)
    if settings.mode != "hardware":
        parser.error("Use real hardware configuration, not simulation")
    robot = settings.robot(args.robot)
    if not robot.device_id:
        parser.error("Robot requires a uniquely configured Xiaozhi head identity")
    async with httpx.AsyncClient() as client:
        head = HttpHead(robot, client, strict_capture=True)
        result = await measure(
            head, robot.id, seconds=args.seconds,
            camera_period_s=args.camera_period,
            status_period_s=args.status_period,
        )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if (result["camera_latency"]["count"] > 0
                 and result["status_latency"]["count"] > 0
                 and not result["camera_error_count"]
                 and not result["status_error_count"]) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
