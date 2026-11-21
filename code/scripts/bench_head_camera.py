"""Read-only live XIAO Sense camera/telemetry bench, no motors or recording.

Run only against a physically connected, authenticated head. The report is
actual HTTP timing, not sensor exposure, AEC, acoustic or charging acceptance.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import stat
import time
from contextlib import aclosing
from pathlib import Path

import httpx
from desk_robot.config import load_settings
from desk_robot.multimodal import _prepare, change_fraction
from desk_robot.transport import HttpHead

ROOT = Path(__file__).resolve().parents[1]

# A stream that delivers a new JPEG after a prolonged blackout is not continuous.
# This is a generous transport probe threshold, not a hardware FPS qualification.
MAX_CAMERA_GAP_S = 1.2


def preflight_private_report(path: Path) -> None:
    """Reject public or existing measurement paths before touching the head."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if (path.parent.is_symlink()
            or stat.S_IMODE(path.parent.stat().st_mode) & 0o077):
        raise ValueError("Camera bench report directory must be private mode 0700")
    if path.exists() or path.is_symlink():
        raise FileExistsError("Camera bench trial report already exists")


def save_private_report(path: Path, report: dict) -> None:
    preflight_private_report(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    with os.fdopen(os.open(path, flags, 0o600), "w", encoding="utf-8") as out:
        json.dump(report, out, indent=2)
        out.write("\n")



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
    stream: bool = False, score_motion: bool = False,
) -> dict:
    """Exercise existing head transport; never send any POST/motion command."""
    if not (0.1 <= seconds <= 3600
            and 0.05 <= camera_period_s <= 10
            and 0.05 <= status_period_s <= 10):
        raise ValueError("Invalid read-only bench duration or periods")
    if score_motion and not stream:
        raise ValueError("Motion scoring requires continuous MJPEG stream")
    camera_times: list[float] = []
    scored_changes: list[float] = []
    scored_brightness_deltas: list[float] = []
    previous_fingerprint: bytes | None = None
    previous_brightness: float | None = None
    last_scored_at = -math.inf
    stream_intervals: list[float] = []
    sense_capture_intervals: list[float] = []
    status_times: list[float] = []
    concurrent_audio_samples: list[tuple[float, dict]] = []
    concurrent_audio_errors: list[str] = []
    read_audio_reference = getattr(head, "audio_reference_status", None)
    camera_sizes: list[int] = []
    camera_errors: list[str] = []
    status_errors: list[str] = []
    camera_error_count = status_error_count = 0
    seen_camera_identities: set[tuple[int, int, int]] = set()
    snapshot_boot: int | None = None
    started = time.monotonic()
    deadline = started + seconds

    async def poll_camera():
        nonlocal camera_error_count, snapshot_boot
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
                    # A fresh boot is allowed by HttpHead transport recovery,
                    # but it invalidates a single uninterrupted camera bench.
                    if snapshot_boot is not None and identity[0] != snapshot_boot:
                        raise RuntimeError("Sense camera rebooted during snapshot bench")
                    if identity in seen_camera_identities:
                        raise ValueError("Head returned duplicate camera identity")
                    snapshot_boot = identity[0]
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

    async def receive_stream():
        """Actually read MJPEG on ONE socket while status polls in parallel.

        No HTTP snapshot requests, images on disk or invented camera timing.
        A quiet or stalled stream remains a measurable bench failure.
        """
        nonlocal camera_error_count, previous_fingerprint
        nonlocal previous_brightness, last_scored_at
        last_frame_at: float | None = None
        last_source_identity: tuple[int, int, int] | None = None
        try:
            async with asyncio.timeout(seconds + 0.5):
                # An interrupted timed bench must release its only head
                # MJPEG HTTP connection before status/report cleanup begins.
                # Async-for by itself does not guarantee generator closure.
                async with aclosing(head.stream_frames()) as stream:
                    async for jpeg, received in stream:
                        if time.monotonic() >= deadline:
                            break
                        if (not isinstance(jpeg, bytes)
                                or not jpeg.startswith(b"\xff\xd8")
                                or not jpeg.endswith(b"\xff\xd9")):
                            raise ValueError("Incomplete JPEG in continuous stream")
                        if last_frame_at is None:
                            if received - started > MAX_CAMERA_GAP_S:
                                raise RuntimeError("Continuous camera stalled before first JPEG")
                        else:
                            if received <= last_frame_at:
                                raise ValueError("Camera stream receipt clock regressed")
                            gap = received - last_frame_at
                            stream_intervals.append(gap)
                            if gap > MAX_CAMERA_GAP_S:
                                raise RuntimeError(
                                    f"Continuous camera stalled for {gap:.2f}s between JPEGs"
                                )
                        last_frame_at = received
                        identity = getattr(head, "_last_camera", None)
                        if identity is None:
                            raise ValueError("Stream has no authenticated frame identity")
                        if identity in seen_camera_identities:
                            raise ValueError("Duplicate live camera frame identity")
                        if last_source_identity is not None:
                            if identity[0] != last_source_identity[0]:
                                raise RuntimeError("Sense camera rebooted during continuous bench")
                            # These are two elapsed times on the SAME Sense boot,
                            # not an ESP-to-Mac absolute clock synchronization.
                            source_gap = (
                                identity[2] - last_source_identity[2]
                            ) / 1_000_000
                            if source_gap <= 0:
                                raise ValueError("Sense frame completion clock regressed")
                            sense_capture_intervals.append(source_gap)
                            if source_gap > MAX_CAMERA_GAP_S:
                                raise RuntimeError(
                                    f"Sense camera capture stalled for {source_gap:.2f}s"
                                )
                        last_source_identity = identity
                        seen_camera_identities.add(identity)
                        camera_sizes.append(len(jpeg))
                        if score_motion and received - last_scored_at >= 1.0:
                            # Instrumented calibration only: decode on the host
                            # without storing JPEGs, running a VLM or sending
                            # any motor/audio command. This costs extra CPU and
                            # must be labeled separately from raw transport FPS.
                            _, fingerprint, brightness = await asyncio.to_thread(
                                _prepare, jpeg
                            )
                            if previous_fingerprint is not None:
                                scored_changes.append(
                                    change_fraction(previous_fingerprint, fingerprint)
                                )
                                scored_brightness_deltas.append(
                                    abs(brightness - previous_brightness)
                                )
                            previous_fingerprint = fingerprint
                            previous_brightness = brightness
                            last_scored_at = received
                # A feed can end exactly at the requested deadline after
                # sending only one early JPEG. Ending on time is not proof
                # that frames kept arriving throughout the bench.
                if last_frame_at is None or deadline - last_frame_at > MAX_CAMERA_GAP_S:
                    raise RuntimeError("Continuous camera ended without recent JPEG")
                if time.monotonic() < deadline - 0.15:
                    raise RuntimeError("Continuous camera stream ended early")
        except TimeoutError:
            # Hitting the deadline is expected only if recent real JPEGs
            # arrived. A stalled stream does not count as continuous video.
            if last_frame_at is None or deadline - last_frame_at > MAX_CAMERA_GAP_S:
                camera_error_count += 1
                camera_errors.append("TimeoutError: continuous camera stalled")
        except Exception as exc:
            camera_error_count += 1
            if len(camera_errors) < 20:
                camera_errors.append(
                    type(exc).__name__ + ": " + str(exc)[:110]
                )

    async def poll_status():
        nonlocal status_error_count
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

    async def poll_concurrent_audio():
        """Observe real codec counters while video runs, never PCM or playback."""
        due = started
        while time.monotonic() < deadline:
            begin = time.monotonic()
            try:
                sample = await asyncio.wait_for(
                    read_audio_reference(),
                    timeout=min(0.8, max(0.05, deadline - begin)),
                )
                if (type(sample) is not dict
                        or sample.get("robot_id") != robot_id
                        or type(sample.get("boot")) is not int
                        or not 0 <= sample["boot"] <= 0xffffffff
                        or sample.get("microphone_privacy_muted") is not False
                        or sample.get("reference_integrity_failed") is not False
                        or sample.get("speaker_playback_verified") is not False
                        or sample.get("aec_physically_qualified") is not False
                        or any(
                            type(sample.get(key)) is not int
                            or not 0 <= sample[key] <= 0xffffffff
                            for key in (
                                "microphone_frames_read",
                                "speaker_frames_accepted",
                                "reference_underflow_reads",
                            )
                        )):
                    raise ValueError("Invalid concurrent Sense AEC receipt")
                if concurrent_audio_samples:
                    previous = concurrent_audio_samples[-1][1]
                    if (sample["boot"] != previous["boot"]
                            or any(sample[key] < previous[key] for key in (
                                "microphone_frames_read",
                                "speaker_frames_accepted",
                                "reference_underflow_reads",
                            ))):
                        raise ValueError("Concurrent Sense AEC reboot or counter regression")
                concurrent_audio_samples.append((time.monotonic(), sample))
            except Exception as exc:
                if len(concurrent_audio_errors) < 20:
                    concurrent_audio_errors.append(
                        type(exc).__name__ + ": " + str(exc)[:110]
                    )
            due = max(due + status_period_s, time.monotonic())
            await asyncio.sleep(max(0, min(deadline, due) - time.monotonic()))

    active_tasks = [
        receive_stream() if stream else poll_camera(), poll_status(),
    ]
    if stream and callable(read_audio_reference):
        active_tasks.append(poll_concurrent_audio())
    await asyncio.gather(*active_tasks)
    # End the camera/status measurement interval BEFORE the optional AEC
    # GET. A slow diagnostic response cannot dilute measured camera FPS.
    elapsed = max(0.001, time.monotonic() - started)
    # Keep the actual Sense AEC counters next to camera/WROOM contention
    # measurements. The optional read is authenticated and does not sample
    # microphone PCM, block the active camera, or certify audible playback.
    audio_reference = None
    audio_reference_error = None
    if callable(read_audio_reference):
        try:
            audio_reference = await asyncio.wait_for(
                read_audio_reference(), timeout=1.0
            )
        except Exception as exc:
            audio_reference_error = type(exc).__name__ + ": " + str(exc)[:110]
    concurrent_audio_delta = None
    if len(concurrent_audio_samples) >= 2:
        first = concurrent_audio_samples[0][1]
        last = concurrent_audio_samples[-1][1]
        concurrent_audio_delta = {
            key: last[key] - first[key]
            for key in (
                "microphone_frames_read", "speaker_frames_accepted",
                "reference_underflow_reads",
            )
        }
    return {
        "concurrent_audio_samples": len(concurrent_audio_samples),
        "concurrent_audio_errors": concurrent_audio_errors[:20],
        "concurrent_audio_counter_delta": concurrent_audio_delta,
        "concurrent_audio_mac_span_ms": (
            round(1000 * (
                concurrent_audio_samples[-1][0] - concurrent_audio_samples[0][0]
            ), 1) if len(concurrent_audio_samples) >= 2 else None
        ),
        "concurrent_audio_driver_activity_observed": (
            stream and concurrent_audio_delta is not None
            and not concurrent_audio_errors
            and concurrent_audio_delta["microphone_frames_read"] > 0
            and concurrent_audio_delta["speaker_frames_accepted"] > 0
            and concurrent_audio_delta["reference_underflow_reads"] == 0
        ),
        "aec_reference_diagnostics": audio_reference,
        "aec_reference_probe_error": audio_reference_error,
        "robot_id": robot_id,
        "elapsed_s": round(elapsed, 3),
        "camera_acquisition_mode": (
            "persistent_mjpeg" if stream else "legacy_snapshot"
        ),
        "requested_camera_fps": None if stream else round(1.0 / camera_period_s, 3),
        "successful_camera_fps": round(len(camera_sizes) / elapsed, 3),
        "camera_frames_received": len(camera_sizes),
        "motion_score_instrumented": score_motion,
        "motion_sample_pair_count": len(scored_changes),
        "motion_changed_fraction_max": (
            round(max(scored_changes), 4) if scored_changes else None
        ),
        "motion_changed_fraction_p95": (
            round(sorted(scored_changes)[math.ceil(.95 * len(scored_changes)) - 1], 4)
            if scored_changes else None
        ),
        "brightness_change_max": (
            round(max(scored_brightness_deltas), 1)
            if scored_brightness_deltas else None
        ),
        "physical_motion_qualified": False,
        "stream_frame_interarrival": summarize(stream_intervals),
        "sense_capture_completion_interarrival": summarize(sense_capture_intervals),
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
    parser.add_argument("--stream", action="store_true",
                        help="Bench the real persistent MJPEG socket instead of snapshots")
    parser.add_argument("--score-motion", action="store_true",
                        help="Instrument 1 FPS camera contrast/motion scores without storing images")
    parser.add_argument("--require-audio-activity", action="store_true",
                        help="Also require actual PDM/I2S counter progress throughout MJPEG")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    # Real A9 qualification always requires continuous consented MJPEG.
    # Snapshot polling remains an internal fake-head test helper only and
    # can never make the physical hardware bench report success.
    if not args.stream:
        parser.error("Physical camera bench requires --stream persistent MJPEG")
    if not 5 <= args.seconds <= 300:
        parser.error("Physical camera bench requires 5..300 seconds")
    if args.score_motion and not args.stream:
        parser.error("--score-motion requires --stream")
    settings = load_settings(args.config)
    if settings.mode != "hardware":
        parser.error("Use real hardware configuration, not simulation")
    robot = settings.robot(args.robot)
    if not robot.device_id:
        parser.error("Robot requires a uniquely configured Xiaozhi head identity")
    preflight_private_report(args.report)
    async with httpx.AsyncClient() as client:
        head = HttpHead(robot, client, strict_capture=True)
        result = await measure(
            head, robot.id, seconds=args.seconds,
            camera_period_s=args.camera_period,
            status_period_s=args.status_period,
            stream=args.stream, score_motion=args.score_motion,
        )
    result["concurrent_audio_required_by_operator"] = args.require_audio_activity
    save_private_report(args.report, result)
    print(json.dumps(result, indent=2))
    return 0 if (result["camera_frames_received"] > 0
                 and result["status_latency"]["count"] > 0
                 and not result["camera_error_count"]
                 and not result["status_error_count"]
                 and (not args.require_audio_activity
                      or result["concurrent_audio_driver_activity_observed"])) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
