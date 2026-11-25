"""Fit candidate MPU6050 handling thresholds from real labeled WROOM samples.

Read-only analysis using the canonical desk_robot.handling raw scaling and
xioTechnologies/Fusion-style stationary gravity baseline. This does not
authorize motors, modify firmware, certify a physical rig or replace a
temperature/axis-mount calibration. Do not use simulated data for release.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

from desk_robot.handling import (
    GYRO_COUNTS_PER_DPS,
    raw_mpu6050,
    trial_low_g_counter,
)


def _finite(value: object) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _unique_handling_trial_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """A physical handling trial must not overwrite earlier sampled facts."""
    fields: dict[str, object] = {}
    for key, value in pairs:
        if key in fields:
            raise ValueError("Duplicate handling trial JSON field: " + key)
        fields[key] = value
    return fields


def _reject_nonfinite_handling_json(token: str) -> None:
    raise ValueError("Nonfinite handling trial JSON constant: " + token)


def load_trial_rows(path: Path) -> list[dict]:
    """Keep actual recorded sample and boot provenance unambiguous."""
    return [
        json.loads(
            row, object_pairs_hook=_unique_handling_trial_fields,
            parse_constant=_reject_nonfinite_handling_json,
        )
        for row in path.read_text(encoding="utf-8").splitlines()
        if row.strip()
    ]


def analyze(records: list[dict]) -> dict:
    """Require real independent WROOM acquisitions from one mounted unit."""
    if not isinstance(records, list) or not 16 <= len(records) <= 500:
        raise ValueError("Need 16..500 actual labeled independent MPU6050 samples")
    groups: dict[str, list[tuple[tuple[float, ...], tuple[float, ...]]]] = {
        "upright": [], "tilted": [], "shaking": [],
    }
    boot_id = firmware = mount = robot_id = None
    last_sample = last_time = None
    previous_low_g_seq = None
    first_sample = first_time = None
    for record in records:
        if (not isinstance(record, dict)
                or type(record.get("label")) is not str
                or record["label"] not in groups):
            raise ValueError("Use upright, tilted or shaking measured labels")
        observed = record.get("time_monotonic_s")
        if not _finite(observed) or observed < 0:
            raise ValueError("Require monotonic physical acquisition time")
        body = record.get("body")
        decoded = raw_mpu6050(body)
        if decoded is None:
            raise ValueError("Each frame needs fresh stationary WROOM MPU6050 evidence")
        observed_robot = body.get("robot_id")
        if "robot_id" in body and (
            type(observed_robot) is not str
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", observed_robot)
        ):
            raise ValueError("Invalid measured-trial robot identity")
        if first_sample is None:
            robot_id = observed_robot
        elif observed_robot != robot_id:
            raise ValueError("Do not mix robot identities or unidentified trials")
        imu = body["imu"]
        seq = trial_low_g_counter(imu)
        if last_sample is not None and seq != previous_low_g_seq:
            raise ValueError("Native low-g status changed during handling trial")
        previous_low_g_seq = seq
        if boot_id is None:
            boot_id = imu["boot_id"]
        if imu["boot_id"] != boot_id:
            raise ValueError("Do not mix WROOM boot identities")
        stamp = imu["sample_ms"]
        if last_time is not None:
            if observed <= last_time or stamp == last_sample:
                raise ValueError("No repeated, reversed or stale IMU conversions")
            if stamp < last_sample:
                # Legitimate near-0xffffffff rollover in same boot context
                is_rollover = (last_sample >= 0xffff0000 and stamp <= 0xffff
                               and ((stamp - last_sample) & 0xffffffff) < 0x7fffffff)
                if not is_rollover:
                    raise ValueError("No repeated, reversed or stale IMU conversions")
            elif stamp - last_sample > 0x7fffffff:
                # Replay of a pre-wrap packet arriving after rollover
                raise ValueError("No repeated, reversed or stale IMU conversions")
        # Device uptime and Mac receipt clocks have different origins, but
        # source acquisition cannot advance by minutes during milliseconds
        # of host observation. Compare cumulative progress, not individual
        # pairs, so repeated small clock jumps cannot evade this check.
        if first_sample is not None:
            source_elapsed_ms = (stamp - first_sample) & 0xffffffff
            host_elapsed_ms = (observed - first_time) * 1000.0
            if source_elapsed_ms > host_elapsed_ms * 1.001 + 3000:
                raise ValueError(
                    "WROOM acquisition clock outpaced host receipt time"
                )
        else:
            first_sample, first_time = stamp, observed
        last_time, last_sample = observed, stamp
        for name, old in (("firmware_commit", firmware), ("mount_id", mount)):
            value = record.get(name)
            if not isinstance(value, str) or not 1 <= len(value.strip()) <= 128:
                raise ValueError(f"Missing measured-trial provenance {name}")
            if old is not None and value != old:
                raise ValueError("Do not combine firmware builds or IMU mount geometry")
        firmware = record["firmware_commit"]
        mount = record["mount_id"]
        accel = decoded[0]
        # The runtime HandlingGate refuses implausible accelerations even
        # with otherwise valid raw bytes. Calibration must be at least as
        # strict as the consumer it proposes to tune.
        if not 0.5 <= math.hypot(*accel) <= 3.5:
            raise ValueError("Implausible MPU6050 acceleration in trial log")
        gyro = tuple(raw / GYRO_COUNTS_PER_DPS for raw in imu["gyro"])
        groups[record["label"]].append((accel, gyro))

    if any(len(groups[label]) < count for label, count in (
            ("upright", 8), ("tilted", 4), ("shaking", 4))):
        raise ValueError("Need at least 8 upright, 4 tilted and 4 shaking trials")
    upright = groups["upright"]
    # The normal baseline is calibrated only while roughly 1g and quiet,
    # rather than learning an intentionally inverted or moving pose.
    if any(not 0.91 <= math.hypot(*acc) <= 1.09
           or math.hypot(*gyro) > 7 for acc, gyro in upright):
        raise ValueError("Upright reference is not stationary and near 1g")
    gravity = tuple(sum(acc[i] for acc, _ in upright) / len(upright)
                    for i in range(3))
    norm = math.hypot(*gravity)
    if not 0.91 <= norm <= 1.09:
        raise ValueError("Upright reference has conflicting gravity vectors")
    baseline = tuple(v / norm for v in gravity)
    bias = tuple(sum(gyro[i] for _, gyro in upright) / len(upright)
                 for i in range(3))
    if any(abs(gyro[i] - bias[i]) > 1.0
           for _, gyro in upright for i in range(3)):
        raise ValueError("Gyroscope offset is not stationary across baseline")

    def rotation(gyro: tuple[float, ...]) -> float:
        return math.hypot(*(value - center for value, center
                            in zip(gyro, bias, strict=True)))

    def angle(acc: tuple[float, ...]) -> float:
        magnitude = math.hypot(*acc)
        dot = sum(a * b for a, b in zip(acc, baseline, strict=True)) / magnitude
        return math.degrees(math.acos(max(-1.0, min(1.0, dot))))

    normal_angles = [angle(acc) for acc, _ in upright]
    tilted = groups["tilted"]
    if any(not 0.75 <= math.hypot(*acc) <= 1.25 or rotation(gyro) > 70
           for acc, gyro in tilted):
        raise ValueError("Tilt trials contain dynamic acceleration or gyro motion")
    tilt_angles = [angle(acc) for acc, _ in tilted]
    min_tilt = min(tilt_angles)
    max_normal = max(normal_angles)
    tilt_choice = max(25.0, (max_normal + min_tilt) / 2)
    if min_tilt - max_normal < 10 or not 25 <= tilt_choice <= 75 or (
            tilt_choice > min_tilt - 5):
        raise ValueError("Measured upright and tilted angles do not separate")

    shake_records = groups["shaking"]
    if any(rotation(gyro) < 50 for _, gyro in shake_records):
        raise ValueError("Shake must contain actual gyro motion")
    shake_deviations = [
        abs(math.hypot(*acc) - 1.0) * 1000
        for acc, _ in shake_records
    ]
    normal_deviations = [
        abs(math.hypot(*acc) - 1.0) * 1000
        for acc, _ in upright
    ]
    lower = min(shake_deviations)
    upper = max(normal_deviations)
    shake_choice = max(300.0, (lower + upper) / 2)
    if lower - upper < 100 or not 300 <= shake_choice <= 1400 or (
            shake_choice > lower - 50):
        raise ValueError("Measured normal and shaken acceleration do not separate")
    return {
        "robot_id": robot_id,
        "firmware_commit": firmware,
        "mount_id": mount,
        "wroom_boot_id": boot_id,
        "sample_counts": {name: len(group) for name, group in groups.items()},
        "gyro_bias_dps": [round(v, 3) for v in bias],
        "tilt_threshold_deg_candidate": round(tilt_choice, 2),
        "shake_delta_mg_candidate": round(shake_choice),
        "normal_tilt_max_deg": round(max_normal, 2),
        "positive_tilt_min_deg": round(min_tilt, 2),
        "normal_accel_deviation_max_mg": round(upper),
        "positive_shake_deviation_min_mg": round(lower),
        "physical_measurements_operator_supplied_not_attested": True,
        "thresholds_physically_qualified": False,
        "motor_authorization": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jsonl", type=Path)
    args = parser.parse_args()
    if not args.jsonl.is_file() or args.jsonl.stat().st_size > 300000:
        raise ValueError("Missing or oversized handling trial log")
    records = load_trial_rows(args.jsonl)
    print(json.dumps(analyze(records), indent=2))


if __name__ == "__main__":
    main()
