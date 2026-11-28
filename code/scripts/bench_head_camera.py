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

# Match the authenticated device AEC diagnostic fields; transport progress
# without consent and codec continuity is not a valid simultaneous A/V trial.
CONCURRENT_AUDIO_COUNTERS = (
    "reference_underflow_reads", "reference_overwrite_reads",
    "discarded_stale_writes", "short_output_writes",
    "microphone_frames_read", "speaker_frames_accepted",
)


def _private_report_directory_fd(parent: Path) -> int:
    """Keep a validated directory open across the actual report creation."""
    # Preserve lexical parent traversal until it has been refused; abspath
    # would hide alias/.. before the filesystem resolves that alias.
    absolute = parent.absolute()
    if ".." in absolute.parts:
        raise ValueError("Unsafe camera bench report parent traversal")
    descriptor = os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for name in absolute.parts[1:]:
            owner = os.fstat(descriptor)
            try:
                entry = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            except FileNotFoundError:
                # Never create missing children until the preceding parent
                # has been opened and verified through its held descriptor.
                os.mkdir(name, mode=0o700, dir_fd=descriptor)
                entry = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            # Stable root-owned system aliases (such as macOS /var) are
            # permitted only under root-owned non-writable directories.
            if stat.S_ISLNK(entry.st_mode) and (
                entry.st_uid != 0 or owner.st_uid != 0
                or stat.S_IMODE(owner.st_mode) & 0o022
            ):
                raise ValueError("Camera bench report directory has unsafe symlink")
            flags = os.O_RDONLY | os.O_DIRECTORY
            if not stat.S_ISLNK(entry.st_mode):
                flags |= os.O_NOFOLLOW
            next_descriptor = os.open(name, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        if stat.S_IMODE(os.fstat(descriptor).st_mode) & 0o077:
            raise ValueError("Camera bench report directory must be private mode 0700")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def preflight_private_report(path: Path) -> None:
    """Reject symlinked or public camera report paths before touching the head."""
    if path.parent.is_symlink():
        raise ValueError("Camera bench report directory must be private mode 0700")
    descriptor = _private_report_directory_fd(path.parent)
    os.close(descriptor)
    if path.exists() or path.is_symlink():
        raise FileExistsError("Camera bench trial report already exists")


def save_private_report(path: Path, report: dict) -> None:
    preflight_private_report(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    descriptor = _private_report_directory_fd(path.parent)
    try:
        with os.fdopen(
            os.open(path.name, flags, 0o600, dir_fd=descriptor),
            "w", encoding="utf-8",
        ) as out:
            json.dump(report, out, indent=2)
            out.write("\n")
    finally:
        os.close(descriptor)



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


def _camera_window_audio_delta(
    samples: list[tuple[float, float, dict]], first: float | None, last: float | None,
) -> tuple[int, dict | None]:
    """Only count codec reads whose entire request interval lies inside video."""
    if first is None or last is None or first >= last:
        return 0, None
    inside = [sample for begin, end, sample in samples if first <= begin <= end <= last]
    if len(inside) < 2:
        return len(inside), None
    return len(inside), {
        key: inside[-1][key] - inside[0][key] for key in CONCURRENT_AUDIO_COUNTERS
    }


def _camera_identity(head) -> tuple[int, int, int]:
    identity = getattr(head, "_last_camera", None)
    if (type(identity) is not tuple or len(identity) != 3
            or any(type(value) is not int for value in identity)
            or not 0 <= identity[0] <= 0xffffffff
            or not 1 <= identity[1] <= 0xffffffff
            or not 1 <= identity[2] <= (1 << 63) - 1):
        raise ValueError("Missing or invalid authenticated camera frame identity")
    return identity


class _BenchRun:
    """One read-only measurement, including all per-run mutable evidence."""

    def __init__(
        self, head, robot_id, seconds, camera_period_s, status_period_s, stream, score_motion,
    ):
        self.head = head
        self.robot_id = robot_id
        self.seconds = seconds
        self.camera_period_s = camera_period_s
        self.status_period_s = status_period_s
        self.stream = stream
        self.score_motion = score_motion
        self.camera_times: list[float] = []
        self.scored_changes: list[float] = []
        self.scored_brightness_deltas: list[float] = []
        self.previous_fingerprint: bytes | None = None
        self.previous_brightness: float | None = None
        self.last_scored_at = -math.inf
        self.stream_intervals: list[float] = []
        self.sense_capture_intervals: list[float] = []
        self.status_times: list[float] = []
        self.concurrent_audio_samples: list[tuple[float, float, dict]] = []
        self.concurrent_audio_errors: list[str] = []
        self.read_audio_reference = getattr(self.head, "audio_reference_status", None)
        self.camera_sizes: list[int] = []
        self.camera_errors: list[str] = []
        self.status_errors: list[str] = []
        self.camera_error_count = self.status_error_count = 0
        self.seen_camera_identities: set[tuple[int, int, int]] = set()
        self.snapshot_boot: int | None = None
        self.snapshot_sequence: int | None = None
        self.snapshot_completed: int | None = None
        self.camera_window_first: float | None = None
        self.camera_window_last: float | None = None
        self.last_frame_at: float | None = None
        self.last_source_identity: tuple[int, int, int] | None = None
        self.started = time.monotonic()
        self.deadline = self.started + self.seconds

    async def poll_camera(self):
        due = self.started
        while time.monotonic() < self.deadline:
            begin = time.monotonic()
            try:
                # Never leave an optional camera HTTP request blocking this
                # bounded, read-only acoustic/contention experiment forever.
                jpeg = await asyncio.wait_for(
                    self.head.snapshot(), timeout=min(4.0, max(0.05, self.deadline - begin))
                )
                if not isinstance(jpeg, bytes) or not jpeg.startswith(b"\xff\xd8") \
                        or not jpeg.endswith(b"\xff\xd9"):
                    raise ValueError("Head returned truncated or non-JPEG data")
                identity = _camera_identity(self.head)
                # A fresh boot is allowed by HttpHead transport recovery,
                # but invalidates a single uninterrupted camera bench.
                if self.snapshot_boot is not None and identity[0] != self.snapshot_boot:
                    raise RuntimeError("Sense camera rebooted during snapshot bench")
                if identity in self.seen_camera_identities:
                    raise ValueError("Head returned duplicate camera identity")
                if self.snapshot_sequence is not None and identity[1] <= self.snapshot_sequence:
                    raise ValueError("Head returned replayed camera sequence")
                if self.snapshot_completed is not None and identity[2] <= self.snapshot_completed:
                    raise ValueError("Sense frame completion clock regressed")
                self.snapshot_boot, self.snapshot_sequence, self.snapshot_completed = identity
                self.seen_camera_identities.add(identity)
                self.camera_sizes.append(len(jpeg))
                self.camera_times.append(time.monotonic() - begin)
            except Exception as exc:
                self.camera_error_count += 1
                if len(self.camera_errors) < 20:
                    self.camera_errors.append(
                        type(exc).__name__ + ": " + str(exc)[:110]
                    )
            # Skip missed slots rather than burst catching up after a
            # stalled JPEG; audio and body telemetry keep priority.
            due = max(due + self.camera_period_s, time.monotonic())
            await asyncio.sleep(max(0, min(self.deadline, due) - time.monotonic()))

    async def receive_stream(self):
        """Actually read MJPEG on ONE socket while status polls in parallel.

        No HTTP snapshot requests, images on disk or invented camera timing.
        A quiet or stalled stream remains a measurable bench failure.
        """
        try:
            async with asyncio.timeout(self.seconds + 0.5):
                # An interrupted timed bench must release its only head
                # MJPEG HTTP connection before status/report cleanup begins.
                # Async-for by itself does not guarantee generator closure.
                async with aclosing(self.head.stream_frames()) as stream:
                    async for jpeg, received in stream:
                        if time.monotonic() >= self.deadline:
                            break
                        self._accept_stream_frame(jpeg, received)
                        await self._score_stream_frame(jpeg, received)
                # A feed can end exactly at the requested deadline after
                # sending only one early JPEG. Ending on time is not proof
                # that frames kept arriving throughout the bench.
                if (self.last_frame_at is None
                        or self.deadline - self.last_frame_at > MAX_CAMERA_GAP_S):
                    raise RuntimeError("Continuous camera ended without recent JPEG")
                if time.monotonic() < self.deadline - 0.15:
                    raise RuntimeError("Continuous camera stream ended early")
        except TimeoutError:
            # Hitting the deadline is expected only if recent real JPEGs
            # arrived. A stalled stream does not count as continuous video.
            if (self.last_frame_at is None
                    or self.deadline - self.last_frame_at > MAX_CAMERA_GAP_S):
                self.camera_error_count += 1
                self.camera_errors.append("TimeoutError: continuous camera stalled")
        except Exception as exc:
            self.camera_error_count += 1
            if len(self.camera_errors) < 20:
                self.camera_errors.append(
                    type(exc).__name__ + ": " + str(exc)[:110]
                )

    def _accept_stream_frame(self, jpeg, received):
        if (not isinstance(jpeg, bytes)
                or not jpeg.startswith(b"\xff\xd8")
                or not jpeg.endswith(b"\xff\xd9")):
            raise ValueError("Incomplete JPEG in continuous stream")
        if (type(received) not in (int, float)
                or not math.isfinite(received)
                or not self.started <= received <= time.monotonic()):
            raise ValueError("Invalid camera stream receipt clock")
        if self.last_frame_at is None:
            if received - self.started > MAX_CAMERA_GAP_S:
                raise RuntimeError("Continuous camera stalled before first JPEG")
        else:
            if received <= self.last_frame_at:
                raise ValueError("Camera stream receipt clock regressed")
            gap = received - self.last_frame_at
            self.stream_intervals.append(gap)
            if gap > MAX_CAMERA_GAP_S:
                raise RuntimeError(
                    f"Continuous camera stalled for {gap:.2f}s between JPEGs"
                )
        self.last_frame_at = received
        self._accept_stream_identity(jpeg, received)

    def _accept_stream_identity(self, jpeg, received):
        identity = _camera_identity(self.head)
        if identity in self.seen_camera_identities:
            raise ValueError("Duplicate live camera frame identity")
        if self.last_source_identity is not None:
            if identity[0] != self.last_source_identity[0]:
                raise RuntimeError("Sense camera rebooted during continuous bench")
            if identity[1] <= self.last_source_identity[1]:
                raise ValueError("Sense camera sequence replayed")
            # These are two elapsed times on the SAME Sense boot,
            # not an ESP-to-Mac absolute clock synchronization.
            source_gap = (
                identity[2] - self.last_source_identity[2]
            ) / 1_000_000
            if source_gap <= 0:
                raise ValueError("Sense frame completion clock regressed")
            self.sense_capture_intervals.append(source_gap)
            if source_gap > MAX_CAMERA_GAP_S:
                raise RuntimeError(
                    f"Sense camera capture stalled for {source_gap:.2f}s"
                )
        self.last_source_identity = identity
        if self.camera_window_first is None:
            self.camera_window_first = received
        self.camera_window_last = received
        self.seen_camera_identities.add(identity)
        self.camera_sizes.append(len(jpeg))

    async def _score_stream_frame(self, jpeg, received):
        if self.score_motion and received - self.last_scored_at >= 1.0:
            # Instrumented calibration only: decode on the host
            # without storing JPEGs, running a VLM or sending
            # any motor/audio command. This costs extra CPU and
            # must be labeled separately from raw transport FPS.
            _, fingerprint, brightness = await asyncio.to_thread(
                _prepare, jpeg
            )
            if self.previous_fingerprint is not None:
                self.scored_changes.append(
                    change_fraction(self.previous_fingerprint, fingerprint)
                )
                self.scored_brightness_deltas.append(
                    abs(brightness - self.previous_brightness)
                )
            self.previous_fingerprint = fingerprint
            self.previous_brightness = brightness
            self.last_scored_at = received

    async def poll_status(self):
        due = self.started
        while time.monotonic() < self.deadline:
            begin = time.monotonic()
            try:
                state = await asyncio.wait_for(
                    self.head.status(), timeout=min(0.8, max(0.05, self.deadline - begin))
                )
                if not isinstance(state, dict) or state.get("robot_id") != self.robot_id:
                    raise ValueError("Head status identity invalid")
                self.status_times.append(time.monotonic() - begin)
            except Exception as exc:
                self.status_error_count += 1
                if len(self.status_errors) < 20:
                    self.status_errors.append(
                        type(exc).__name__ + ": " + str(exc)[:110]
                    )
            due = max(due + self.status_period_s, time.monotonic())
            await asyncio.sleep(max(0, min(self.deadline, due) - time.monotonic()))

    async def poll_concurrent_audio(self):
        """Observe real codec counters while video runs, never PCM or playback."""
        due = self.started
        while time.monotonic() < self.deadline:
            begin = time.monotonic()
            try:
                sample = await asyncio.wait_for(
                    self.read_audio_reference(),
                    timeout=min(0.8, max(0.05, self.deadline - begin)),
                )
                self._validate_audio_sample(sample)
                self.concurrent_audio_samples.append((begin, time.monotonic(), sample))
            except Exception as exc:
                if len(self.concurrent_audio_errors) < 20:
                    self.concurrent_audio_errors.append(
                        type(exc).__name__ + ": " + str(exc)[:110]
                    )
            due = max(due + self.status_period_s, time.monotonic())
            await asyncio.sleep(max(0, min(self.deadline, due) - time.monotonic()))

    def _validate_audio_sample(self, sample):
        if (type(sample) is not dict
                or sample.get("robot_id") != self.robot_id
                or type(sample.get("boot")) is not int
                or not 0 <= sample["boot"] <= 0xffffffff
                or sample.get("microphone_privacy_muted") is not False
                or type(sample.get("microphone_privacy_epoch")) is not int
                or not 0 <= sample["microphone_privacy_epoch"] <= 0xffffffff
                or sample.get("reference_integrity_failed") is not False
                or sample.get("speaker_playback_verified") is not False
                or sample.get("aec_physically_qualified") is not False
                or any(
                    type(sample.get(key)) is not int
                    or not 0 <= sample[key] <= 0xffffffff
                    for key in CONCURRENT_AUDIO_COUNTERS
                )):
            raise ValueError("Invalid concurrent Sense AEC receipt")
        if self.concurrent_audio_samples:
            previous = self.concurrent_audio_samples[-1][2]
            if (sample["boot"] != previous["boot"]
                    # The mic can be revoked and regranted between two
                    # unmuted polls. That interval cannot pass A/V.
                    or sample["microphone_privacy_epoch"]
                    != previous["microphone_privacy_epoch"]
                    or any(sample[key] < previous[key]
                           for key in CONCURRENT_AUDIO_COUNTERS)):
                raise ValueError("Concurrent Sense AEC reboot or counter regression")

    async def run_workers(self):
        active_tasks = [
            self.receive_stream() if self.stream else self.poll_camera(), self.poll_status(),
        ]
        if self.stream and callable(self.read_audio_reference):
            active_tasks.append(self.poll_concurrent_audio())
        tasks = [asyncio.create_task(worker) for worker in active_tasks]
        try:
            await asyncio.gather(*tasks)
        finally:
            # A child cancellation does not cancel its gather siblings. Close
            # the camera lease and drain all polls before returning to the caller.
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def probe_audio(self):
        # Keep the actual Sense AEC counters next to camera/WROOM contention
        # measurements. The optional read is authenticated and does not sample
        # microphone PCM, block the active camera, or certify audible playback.
        audio_reference = None
        audio_reference_error = None
        if callable(self.read_audio_reference):
            try:
                audio_reference = await asyncio.wait_for(
                    self.read_audio_reference(), timeout=1.0
                )
            except Exception as exc:
                audio_reference_error = type(exc).__name__ + ": " + str(exc)[:110]
        return audio_reference, audio_reference_error

    def _audio_report(self, audio_reference, audio_reference_error):
        concurrent_audio_delta = None
        if len(self.concurrent_audio_samples) >= 2:
            first = self.concurrent_audio_samples[0][2]
            last = self.concurrent_audio_samples[-1][2]
            concurrent_audio_delta = {
                key: last[key] - first[key]
                for key in CONCURRENT_AUDIO_COUNTERS
            }
        window_count, window_delta = _camera_window_audio_delta(
            self.concurrent_audio_samples, self.camera_window_first, self.camera_window_last,
        )
        # AEC samples from a different Sense boot cannot witness activity
        # alongside these camera frames, even when both counter sets advance.
        camera_boots = {identity[0] for identity in self.seen_camera_identities}
        audio_boot_matches_camera = (
            len(camera_boots) == 1 and bool(self.concurrent_audio_samples)
            and self.concurrent_audio_samples[0][2]["boot"] in camera_boots
        )
        return {
            "concurrent_audio_samples": len(self.concurrent_audio_samples),
            "concurrent_audio_errors": self.concurrent_audio_errors[:20],
            "concurrent_audio_counter_delta": concurrent_audio_delta,
            "camera_window_audio_samples": window_count,
            "camera_window_audio_counter_delta": window_delta,
            "concurrent_audio_boot_matches_camera": audio_boot_matches_camera,
            "concurrent_audio_mac_span_ms": (
                round(1000 * (
                    self.concurrent_audio_samples[-1][1] - self.concurrent_audio_samples[0][1]
                ), 1) if len(self.concurrent_audio_samples) >= 2 else None
            ),
            "concurrent_audio_driver_activity_observed": (
                self.stream and concurrent_audio_delta is not None
                and not self.concurrent_audio_errors
                and audio_boot_matches_camera
                and window_delta is not None
                and window_delta["microphone_frames_read"] > 0
                and window_delta["speaker_frames_accepted"] > 0
                and all(concurrent_audio_delta[key] == 0 for key in (
                    "reference_underflow_reads", "reference_overwrite_reads",
                    "discarded_stale_writes", "short_output_writes",
                ))
            ),
            "aec_reference_diagnostics": audio_reference,
            "aec_reference_probe_error": audio_reference_error,
        }

    def report(self, elapsed, audio_reference, audio_reference_error):
        return {
            **self._audio_report(audio_reference, audio_reference_error),
            "robot_id": self.robot_id,
            "elapsed_s": round(elapsed, 3),
            "camera_acquisition_mode": (
                "persistent_mjpeg" if self.stream else "legacy_snapshot"
            ),
            "requested_camera_fps": None if self.stream else round(1.0 / self.camera_period_s, 3),
            "successful_camera_fps": round(len(self.camera_sizes) / elapsed, 3),
            "camera_frames_received": len(self.camera_sizes),
            "motion_score_instrumented": self.score_motion,
            "motion_sample_pair_count": len(self.scored_changes),
            "motion_changed_fraction_max": (
                round(max(self.scored_changes), 4) if self.scored_changes else None
            ),
            "motion_changed_fraction_p95": (
                round(sorted(self.scored_changes)[math.ceil(.95 * len(self.scored_changes)) - 1], 4)
                if self.scored_changes else None
            ),
            "brightness_change_max": (
                round(max(self.scored_brightness_deltas), 1)
                if self.scored_brightness_deltas else None
            ),
            "physical_motion_qualified": False,
            "stream_frame_interarrival": summarize(self.stream_intervals),
            "sense_capture_completion_interarrival": summarize(self.sense_capture_intervals),
            "camera_latency": summarize(self.camera_times),
            "status_latency": summarize(self.status_times),
            "largest_jpeg_bytes": max(self.camera_sizes, default=0),
            "distinct_source_camera_identities": len(self.seen_camera_identities),
            "camera_errors": self.camera_errors[:20],
            "camera_error_count": self.camera_error_count,
            "status_errors": self.status_errors[:20],
            "status_error_count": self.status_error_count,
            "camera_transport_probe_only": True,
            "sensor_exposure_clock_synchronized": False,
            "physical_aec_latency_measured": False,
            "speaker_silence_verified": False,
            "charging_verified": False,
            "assembly_ready": False,
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
    run = _BenchRun(
        head, robot_id, seconds, camera_period_s, status_period_s, stream, score_motion,
    )
    await run.run_workers()
    # End the camera/status measurement interval BEFORE the optional AEC
    # GET. A slow diagnostic response cannot dilute measured camera FPS.
    elapsed = max(0.001, time.monotonic() - run.started)
    audio_reference, audio_reference_error = await run.probe_audio()
    return run.report(elapsed, audio_reference, audio_reference_error)


def bench_passed(report: dict, *, require_audio: bool) -> bool:
    """Transport-only and explicitly combined digital audio trials stay distinct."""
    return (
        report["camera_frames_received"] > 0
        and report["status_latency"]["count"] > 0
        and not report["camera_error_count"]
        and not report["status_error_count"]
        and (not require_audio or report["concurrent_audio_driver_activity_observed"])
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config/local.toml")
    parser.add_argument("--robot", required=True)
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--camera-period", type=float, default=1.0)
    parser.add_argument("--status-period", type=float, default=0.2)
    parser.add_argument("--stream", action="store_true",
                        help="Bench the real persistent MJPEG socket instead of snapshots")
    parser.add_argument(
        "--score-motion", action="store_true",
        help="Instrument 1 FPS camera contrast/motion scores without storing images",
    )
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
    async with httpx.AsyncClient(trust_env=False) as client:
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
    return 0 if bench_passed(result, require_audio=args.require_audio_activity) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
