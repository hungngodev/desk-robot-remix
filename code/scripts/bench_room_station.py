"""Bounded read-only USB evidence capture for the shared Feather room station.

This collects source/receive statistics, not raw environmental history,
sensor identity proof, voltage, current, temperature or charge qualification.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import stat
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from desk_robot.room_station import SENSORS, STATION, RoomObservation, RoomSerialFeed
from desk_robot.serial_device import is_local_serial_path

# Twice the nominal maximum one-hour report count, independent of USB rate.
MAX_CAPTURE_FRAMES = 7200


def _git_sha() -> str | None:
    """Stamp an exact source commit only for a verified clean checkout.

    A valid HEAD SHA alone does not identify locally modified bench code,
    changed hardware profiles, or untracked source files.
    """
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True, text=True, check=False, timeout=2,
        )
        changes = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True, text=True, check=False, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    candidate = revision.stdout.strip()
    return (candidate if revision.returncode == 0 and len(candidate) == 40
            and all(c in "0123456789abcdef" for c in candidate)
            and changes.returncode == 0 and not changes.stdout.strip()
            else None)


def _validate_capture_args(port: str, seconds: float) -> None:
    if not is_local_serial_path(port):
        raise ValueError("Explicit /dev/ room station USB port required")
    if not _is_finite_number(seconds) or not 0.5 <= seconds <= 3600:
        raise ValueError("Bounded live station trial must last 0.5 to 3600 seconds")


def _is_finite_number(value: object) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _is_uint32(value: object) -> bool:
    return type(value) is int and 0 <= value <= 0xffffffff


def _validate_observation(item: RoomObservation) -> None:
    if (not isinstance(item, RoomObservation) or item.motion_authorized
            or item.charging_authorized or item.person_identified):
        raise ValueError("Room USB data must never carry action or identity authority")
    if not _is_uint32(item.seq):
        raise ValueError("Invalid room station bench sequence")
    if not _is_uint32(item.at_ms):
        raise ValueError("Invalid room station bench source timestamp")
    if not _is_finite_number(item.received_at):
        raise ValueError("Invalid room station bench receive clock")


def _validated_sensor_samples(item: RoomObservation, previous_samples: dict[str, int]) -> dict:
    # Stage an entire decoded observation before counting anything.
    if not isinstance(item.readings, dict) or set(item.readings) != set(SENSORS):
        raise ValueError("Incomplete room station bench sensor record")
    samples = {}
    for name in SENSORS:
        reading = item.readings[name]
        if not isinstance(reading, dict) or type(reading.get("valid")) is not bool:
            raise ValueError("Invalid room station bench sensor validity")
        if not reading["valid"]:
            continue
        sample_ms = reading.get("sample_ms")
        if not _is_uint32(sample_ms):
            raise ValueError("Invalid room sensor acquisition clock")
        previous = previous_samples.get(name)
        if previous is not None and ((sample_ms - previous) & 0xffffffff) >= 0x80000000:
            raise ValueError("Backwards room sensor acquisition clock")
        samples[name] = sample_ms
    return samples


class _CaptureFrames:
    """Bounded, atomically validated observations for one USB epoch."""

    def __init__(self) -> None:
        self.received_at: list[float] = []
        self.sequence: list[int] = []
        self.station_ms: list[int] = []
        self.sensor_counts = dict.fromkeys(SENSORS, 0)
        self.new_sensor_acquisitions = dict.fromkeys(SENSORS, 0)
        self.reused_sensor_samples = dict.fromkeys(SENSORS, 0)
        self.last_sensor_sample_ms: dict[str, int] = {}
        self.capture_limit_exceeded = False

    def observe(self, item: RoomObservation) -> None:
        if len(self.sequence) >= MAX_CAPTURE_FRAMES:
            self.capture_limit_exceeded = True
            raise ValueError("Room station bench frame budget exceeded")
        _validate_observation(item)
        samples = _validated_sensor_samples(item, self.last_sensor_sample_ms)
        # No counter or acquisition baseline changes before all sensors validate.
        self.received_at.append(item.received_at)
        self.sequence.append(item.seq)
        self.station_ms.append(item.at_ms)
        for name, sample_ms in samples.items():
            self.sensor_counts[name] += 1
            if self.last_sensor_sample_ms.get(name) == sample_ms:
                self.reused_sensor_samples[name] += 1
            else:
                self.new_sensor_acquisitions[name] += 1
                self.last_sensor_sample_ms[name] = sample_ms


class _ReceiveTiming:
    """Mac clock chronology and silence, including capture boundaries."""

    def __init__(self, received_at: list[float], start: float, finished: float) -> None:
        self.elapsed = max(0.0, finished - start)
        self.gaps = [b - a for a, b in zip(received_at[:-1], received_at[1:], strict=True)]
        self.leading = max(0.0, received_at[0] - start) if received_at else None
        self.trailing = max(0.0, finished - received_at[-1]) if received_at else None
        self.silence_windows = list(self.gaps)
        if self.leading is not None:
            self.silence_windows.extend((self.leading, self.trailing))
        elif self.elapsed > 0:
            self.silence_windows.append(self.elapsed)
        self.consistent = (
            start <= finished
            and all(start <= at <= finished for at in received_at)
            and all(b >= a for a, b in
                    zip(received_at[:-1], received_at[1:], strict=True))
        )

    def silence_bounded(self) -> bool:
        return (
            all(0.0 < gap <= 1.5 for gap in self.gaps)
            and self.leading is not None and 0.0 <= self.leading <= 1.5
            and self.trailing is not None and 0.0 <= self.trailing <= 1.5
        )


def _station_metrics(frames: _CaptureFrames) -> tuple[int, bool]:
    # Sequence gaps and source cadence are independent of Mac receipt timing.
    # Unsigned differences preserve legitimate millis rollover.
    sequence = frames.sequence
    station_ms = frames.station_ms
    missing = sum(max(0, ((b - a) & 0xffffffff) - 1)
                  for a, b in zip(sequence[:-1], sequence[1:], strict=True))
    station_gaps = [(b - a) & 0xffffffff
                    for a, b in zip(station_ms[:-1], station_ms[1:], strict=True)]
    cadence = bool(station_gaps) and all(1000 <= gap <= 1500 for gap in station_gaps)
    return missing, cadence


def _one_hour_continuity_pass(
    seconds: float, frames: _CaptureFrames, timing: _ReceiveTiming,
    reader: RoomSerialFeed, error: str | None, missing: int, cadence: bool,
) -> bool:
    # Diagnostic only. This cannot qualify sensor accuracy, power or motion.
    sequence = frames.sequence
    return (
        seconds == 3600
        and timing.elapsed >= 3600
        and len(sequence) >= 3600
        and missing == 0
        # A repeated sequence ID can have zero missing sequences.
        and all(((b - a) & 0xffffffff) == 1
                for a, b in zip(sequence[:-1], sequence[1:], strict=True))
        and not frames.capture_limit_exceeded
        and reader.rejected == 0
        and reader.callback_failures == 0
        and error is None
        and timing.consistent
        and cadence
        and timing.silence_bounded()
    )


def _milliseconds(value: float | None) -> float | None:
    return round(value * 1000, 1) if value is not None else None


def _capture_report(
    port: str, seconds: float, frames: _CaptureFrames, timing: _ReceiveTiming,
    reader: RoomSerialFeed, error: str | None,
) -> dict:
    missing, cadence = _station_metrics(frames)
    continuity = _one_hour_continuity_pass(seconds, frames, timing, reader, error, missing, cadence)
    sequence = frames.sequence
    return {
        "station": STATION,
        "source_commit": _git_sha(),
        "usb_port": port,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "requested_seconds": seconds,
        "observed_seconds": round(timing.elapsed, 3),
        "accepted_frames": len(sequence),
        "capture_limit_exceeded": frames.capture_limit_exceeded,
        "rejected_frames": reader.rejected,
        "callback_failures": reader.callback_failures,
        "serial_error_type": error,
        "first_station_sequence": sequence[0] if sequence else None,
        "last_station_sequence": sequence[-1] if sequence else None,
        "missing_station_sequences": missing,
        "largest_mac_receive_gap_ms": _milliseconds(max(timing.gaps, default=None)),
        "initial_receive_silence_ms": _milliseconds(timing.leading),
        "trailing_receive_silence_ms": _milliseconds(timing.trailing),
        "largest_mac_receive_silence_ms": _milliseconds(max(timing.silence_windows, default=None)),
        "valid_sensor_frames": frames.sensor_counts,
        "new_sensor_acquisitions": frames.new_sensor_acquisitions,
        "reused_sensor_samples": frames.reused_sensor_samples,
        "one_hour_usb_continuity_screen_pass": continuity,
        "receive_clock_consistent": timing.consistent,
        "station_report_cadence_consistent": cadence,
        "read_only_usb_sample_captured": (
            bool(sequence) and timing.consistent and error is None
            and not frames.capture_limit_exceeded and reader.callback_failures == 0
        ),
        "device_identity_authenticated": False,
        "sensor_accuracy_physically_qualified": False,
        "station_power_physically_qualified": False,
        "charging_verified": False,
        "motion_authorized": False,
        "notes": ("USB counts and Mac receive gaps only. Measure actual rail voltage, "
                  "regulator temperature, pack current, wiring and sensor calibration "
                  "with qualified instruments before hardware release."),
    }


def capture(
    port: str, *, seconds: float,
    feed_factory: Callable = RoomSerialFeed,
    clock: Callable[[], float] = time.monotonic,
) -> dict:
    """Take one serial epoch. A timeout or failure never promotes hardware."""
    _validate_capture_args(port, seconds)
    frames = _CaptureFrames()
    reader = feed_factory(port, frames.observe)
    start = clock()
    deadline = start + seconds
    error = None
    try:
        # One connection; no automatic reconnect that could mask USB outages.
        reader._read_port(lambda: not frames.capture_limit_exceeded and clock() < deadline)
    except Exception as exc:
        error = type(exc).__name__
    timing = _ReceiveTiming(frames.received_at, start, clock())
    return _capture_report(port, seconds, frames, timing, reader, error)


def _private_report_directory_fd(parent: Path) -> int:
    """Open the real target directory without trusting replaceable links."""
    # Path.absolute preserves lexical ".." segments. os.path.abspath would
    # erase them before inspection even though the filesystem resolves links
    # before a parent traversal.
    absolute = parent.absolute()
    if ".." in absolute.parts:
        raise ValueError("Unsafe room bench report parent traversal")
    checkout_path = Path(__file__).resolve().parents[2]
    resolved = absolute.resolve()
    if resolved == checkout_path or checkout_path in resolved.parents:
        raise ValueError("Room bench reports must remain outside the Git checkout")
    checkout = checkout_path.stat()
    descriptor = os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for name in absolute.parts[1:]:
            # Each parent is already held open and checked. Creating the next
            # directory through that descriptor prevents a rejected symlink
            # ancestor from creating files or directories in its target.
            ancestor = os.fstat(descriptor)
            if (ancestor.st_dev, ancestor.st_ino) == (checkout.st_dev, checkout.st_ino):
                raise ValueError("Room bench reports must remain outside the Git checkout")
            try:
                entry = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            except FileNotFoundError:
                os.mkdir(name, mode=0o700, dir_fd=descriptor)
                entry = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            # Honor only system-owned aliases under nonwritable root-owned
            # parents, including macOS /var. Reject mutable user symlinks.
            if stat.S_ISLNK(entry.st_mode) and (
                entry.st_uid != 0 or ancestor.st_uid != 0
                or stat.S_IMODE(ancestor.st_mode) & 0o022
            ):
                raise ValueError("Unsafe room bench report ancestor symlink")
            flags = os.O_RDONLY | os.O_DIRECTORY
            if not stat.S_ISLNK(entry.st_mode):
                flags |= os.O_NOFOLLOW
            next_descriptor = os.open(name, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        final = os.fstat(descriptor)
        if (final.st_dev, final.st_ino) == (checkout.st_dev, checkout.st_ino):
            raise ValueError("Room bench reports must remain outside the Git checkout")
        if stat.S_IMODE(final.st_mode) & 0o077:
            raise ValueError("Room bench report directory must be private mode 0700")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def preflight_private_bench_report(path: Path) -> None:
    """Refuse unsafe or occupied report paths before opening the USB port."""
    if path.parent.is_symlink():
        raise ValueError("Unsafe room bench report directory symlink")
    directory_fd = _private_report_directory_fd(path.parent)
    try:
        # The final writer repeats every check and uses exclusive O_NOFOLLOW,
        # so replacement between preflight and capture cannot overwrite data.
        try:
            os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        raise FileExistsError(f"Room bench report already exists: {path.name}")
    finally:
        os.close(directory_fd)


def save_private_bench_report(path: Path, report: dict) -> None:
    """Record only a new private USB receipt, never overwrite old evidence."""
    if path.parent.is_symlink():
        raise ValueError("Unsafe room bench report directory symlink")
    directory_fd = _private_report_directory_fd(path.parent)
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        with os.fdopen(
            os.open(path.name, flags, 0o600, dir_fd=directory_fd),
            "w", encoding="utf-8",
        ) as output:
            json.dump(report, output, indent=2)
            output.write("\n")
    finally:
        os.close(directory_fd)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="Actual /dev/ USB serial port")
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        _validate_capture_args(args.port, args.seconds)
    except ValueError as exc:
        parser.error(str(exc))
    preflight_private_bench_report(args.report)
    result = capture(args.port, seconds=args.seconds)
    save_private_bench_report(args.report, result)
    print(json.dumps(result, indent=2))
    # Keep failed diagnostic receipts, but never signal shell success for them.
    if (result.get("read_only_usb_sample_captured") is not True
            or (args.seconds == 3600
                and result.get("one_hour_usb_continuity_screen_pass") is not True)):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
