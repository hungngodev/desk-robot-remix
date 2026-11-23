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


def capture(
    port: str, *, seconds: float,
    feed_factory: Callable = RoomSerialFeed,
    clock: Callable[[], float] = time.monotonic,
) -> dict:
    """Take one serial epoch. A timeout or failure never promotes hardware."""
    if not isinstance(port, str) or not port.startswith("/dev/"):
        raise ValueError("Explicit /dev/ room station USB port required")
    # Huge integers can raise OverflowError during math.isfinite().
    # Treat impossible durations as rejected input, not a crashed bench.
    try:
        finite_duration = type(seconds) in (int, float) and math.isfinite(seconds)
    except OverflowError:
        finite_duration = False
    if not finite_duration or not 0.5 <= seconds <= 3600:
        raise ValueError("Bounded live station trial must last 0.5 to 3600 seconds")

    received_at: list[float] = []
    sequence: list[int] = []
    sensor_counts = dict.fromkeys(SENSORS, 0)
    new_sensor_acquisitions = dict.fromkeys(SENSORS, 0)
    reused_sensor_samples = dict.fromkeys(SENSORS, 0)
    last_sensor_sample_ms: dict[str, int] = {}

    def observed(item: RoomObservation) -> None:
        if (not isinstance(item, RoomObservation) or item.motion_authorized
                or item.charging_authorized or item.person_identified):
            raise ValueError("Room USB data must never carry action or identity authority")
        # Stage an entire decoded observation before counting anything.
        # If an alternate reader supplies an incomplete record, a callback
        # failure must never be counted as a successful physical USB receipt.
        if not isinstance(item.readings, dict) or set(item.readings) != set(SENSORS):
            raise ValueError("Incomplete room station bench sensor record")
        valid_by_sensor = {}
        sample_by_sensor = {}
        for name in SENSORS:
            reading = item.readings[name]
            if not isinstance(reading, dict) or type(reading.get("valid")) is not bool:
                raise ValueError("Invalid room station bench sensor validity")
            valid_by_sensor[name] = reading["valid"]
            if reading["valid"]:
                sample_ms = reading.get("sample_ms")
                if type(sample_ms) is not int or not 0 <= sample_ms <= 0xffffffff:
                    raise ValueError("Invalid room sensor acquisition clock")
                previous = last_sensor_sample_ms.get(name)
                if previous is not None:
                    advance = (sample_ms - previous) & 0xffffffff
                    if advance >= 0x80000000:
                        raise ValueError("Backwards room sensor acquisition clock")
                sample_by_sensor[name] = sample_ms
        received_at.append(item.received_at)
        sequence.append(item.seq)
        for name, valid in valid_by_sensor.items():
            if valid:
                sensor_counts[name] += 1
                sample_ms = sample_by_sensor[name]
                if last_sensor_sample_ms.get(name) == sample_ms:
                    reused_sensor_samples[name] += 1
                else:
                    new_sensor_acquisitions[name] += 1
                    last_sensor_sample_ms[name] = sample_ms

    reader = feed_factory(port, observed)
    start = clock()
    deadline = start + seconds
    error = None
    try:
        # Use the same decoder, newline and replay fencing as runtime. One
        # connection, no automatic reconnect that could mask USB outages.
        reader._read_port(lambda: clock() < deadline)
    except Exception as exc:
        error = type(exc).__name__

    finished = clock()
    elapsed = max(0.0, finished - start)
    gaps = [b - a for a, b in zip(received_at[:-1], received_at[1:], strict=True)]
    # A station that goes silent after one successful packet has no adjacent
    # receive gap. Include start and end of the actual trial for continuity.
    leading = max(0.0, received_at[0] - start) if received_at else None
    trailing = max(0.0, finished - received_at[-1]) if received_at else None
    silence_windows = list(gaps)
    if leading is not None:
        silence_windows.extend((leading, trailing))
    elif elapsed > 0:
        silence_windows.append(elapsed)
    # Preserve observed station sequence gaps independently of HTTP/USB
    # receipt cadence. Do not interpret any gap as a motor safety measurement.
    missing = sum(max(0, ((b - a) & 0xffffffff) - 1)
                  for a, b in zip(sequence[:-1], sequence[1:], strict=True))
    # Diagnostic only: a full one-hour USB continuity trial must contain
    # at least 3,600 distinct consecutive nominal one-second reports with
    # bounded Mac receive silence. This cannot qualify radar accuracy,
    # environmental calibration, power, charger, or any motion authority.
    one_hour_usb_continuity_screen_pass = (
        seconds == 3600
        and elapsed >= 3600
        and len(sequence) >= 3600
        and missing == 0
        # Sequence gap totals alone cannot reject a duplicated extra report:
        # 3,601 receptions with one repeated uint32 ID still have zero gaps.
        and all(((b - a) & 0xffffffff) == 1
                for a, b in zip(sequence[:-1], sequence[1:], strict=True))
        and reader.rejected == 0
        and reader.callback_failures == 0
        and error is None
        and start <= received_at[0] <= received_at[-1] <= finished
        and all(0.0 < gap <= 1.5 for gap in gaps)
        and leading is not None and 0.0 <= leading <= 1.5
        and trailing is not None and 0.0 <= trailing <= 1.5
    )
    return {
        "station": STATION,
        "source_commit": _git_sha(),
        "usb_port": port,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "requested_seconds": seconds,
        "observed_seconds": round(elapsed, 3),
        "accepted_frames": len(sequence),
        "rejected_frames": reader.rejected,
        "callback_failures": reader.callback_failures,
        "serial_error_type": error,
        "first_station_sequence": sequence[0] if sequence else None,
        "last_station_sequence": sequence[-1] if sequence else None,
        "missing_station_sequences": missing,
        "largest_mac_receive_gap_ms": round(max(gaps) * 1000, 1) if gaps else None,
        "initial_receive_silence_ms": round(leading * 1000, 1) if leading is not None else None,
        "trailing_receive_silence_ms": round(trailing * 1000, 1) if trailing is not None else None,
        "largest_mac_receive_silence_ms": (
            round(max(silence_windows) * 1000, 1) if silence_windows else None
        ),
        "valid_sensor_frames": sensor_counts,
        "new_sensor_acquisitions": new_sensor_acquisitions,
        "reused_sensor_samples": reused_sensor_samples,
        "one_hour_usb_continuity_screen_pass": one_hour_usb_continuity_screen_pass,
        "read_only_usb_sample_captured": (
            bool(sequence) and error is None and reader.callback_failures == 0
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


def _private_report_directory_fd(parent: Path) -> int:
    """Open the real target directory without trusting replaceable links."""
    # Path.absolute preserves lexical ".." segments. os.path.abspath would
    # erase them before inspection even though the filesystem resolves links
    # before a parent traversal.
    absolute = parent.absolute()
    if ".." in absolute.parts:
        raise ValueError("Unsafe room bench report parent traversal")
    descriptor = os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for name in absolute.parts[1:]:
            # Each parent is already held open and checked. Creating the next
            # directory through that descriptor prevents a rejected symlink
            # ancestor from creating files or directories in its target.
            ancestor = os.fstat(descriptor)
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
        if stat.S_IMODE(os.fstat(descriptor).st_mode) & 0o077:
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
    preflight_private_bench_report(args.report)
    result = capture(args.port, seconds=args.seconds)
    save_private_bench_report(args.report, result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
