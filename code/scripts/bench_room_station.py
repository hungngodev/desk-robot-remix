"""Bounded read-only USB evidence capture for the shared Feather room station.

This collects source/receive statistics, not raw environmental history,
sensor identity proof, voltage, current, temperature or charge qualification.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from desk_robot.room_station import SENSORS, STATION, RoomObservation, RoomSerialFeed


def _git_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True, text=True, check=False, timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    candidate = result.stdout.strip()
    return (candidate if result.returncode == 0 and len(candidate) == 40
            and all(c in "0123456789abcdef" for c in candidate) else None)


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
        for name in SENSORS:
            reading = item.readings[name]
            if not isinstance(reading, dict) or type(reading.get("valid")) is not bool:
                raise ValueError("Invalid room station bench sensor validity")
            valid_by_sensor[name] = reading["valid"]
        received_at.append(item.received_at)
        sequence.append(item.seq)
        for name, valid in valid_by_sensor.items():
            if valid:
                sensor_counts[name] += 1

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
        "read_only_usb_sample_captured": bool(sequence) and error is None,
        "device_identity_authenticated": False,
        "sensor_accuracy_physically_qualified": False,
        "station_power_physically_qualified": False,
        "charging_verified": False,
        "motion_authorized": False,
        "notes": ("USB counts and Mac receive gaps only. Measure actual rail voltage, "
                  "regulator temperature, pack current, wiring and sensor calibration "
                  "with qualified instruments before hardware release."),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="Actual /dev/ USB serial port")
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = capture(args.port, seconds=args.seconds)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
