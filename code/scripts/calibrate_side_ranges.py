#!/usr/bin/env python3
"""Analyze real labeled left/right/rear VL53L0X raw WROOM measurements.

Input is JSONL with robot_id, direction in left/right/rear, label in near/far,
and unmodified side_ranges from real GET /v1/robots/{id}/status. A human
must capture at least 20 distinct near and far sample times per direction.
The output is a *candidate* threshold, not physical certification or a
firmware movement calibration. No motors or chargers are ever activated.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

SIDE = {"left": 0, "right": 1, "rear": 2}


def _unique_side_trial_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """No last-key-wins change to a physical ToF trial or sensor mask."""
    fields: dict[str, object] = {}
    for key, value in pairs:
        if key in fields:
            raise ValueError("Duplicate side-range trial JSON field: " + key)
        fields[key] = value
    return fields


def _reject_nonfinite_side_trial_json(token: str) -> None:
    raise ValueError("Nonfinite side-range trial JSON constant: " + token)


def _finite_side_trial_float(token: str) -> float:
    value = float(token)
    if not math.isfinite(value):
        raise ValueError("Nonfinite side-range trial JSON number: " + token)
    return value


def load_trial_rows(path: Path) -> list[dict]:
    """Preserve raw left/right/rear trial identity before threshold fitting."""
    return [
        json.loads(
            line, object_pairs_hook=_unique_side_trial_fields,
            parse_constant=_reject_nonfinite_side_trial_json,
            parse_float=_finite_side_trial_float,
        )
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def percentile(values: list[int], proportion: float) -> int:
    if not values or not 0 <= proportion <= 1:
        raise ValueError("Missing samples or invalid percentile")
    sorted_values = sorted(values)
    # Conservative nearest rank, rather than interpolating fake mm samples.
    index = math.ceil(proportion * len(values)) - 1
    return sorted_values[max(0, min(len(sorted_values) - 1, index))]


def _capture_provenance(line: dict, age_ms: int) -> dict | None:
    """Validate claimed capture metadata without authenticating physical evidence."""
    keys = ("firmware_commit", "mount_id", "captured_at_monotonic_s",
            "request_elapsed_ms", "surface_condition")
    if not any(key in line for key in keys):
        return None  # Legacy raw rows remain candidate-only, with unknown provenance.
    firmware, mount, captured, elapsed, surface = (line.get(key) for key in keys)
    if (any(type(value) is not str or not 1 <= len(value.strip()) <= 128
            for value in (firmware, mount))
            or type(captured) not in (int, float) or not 0 <= captured < math.inf
            or ("surface_condition" in line and (
                type(surface) is not str or not 1 <= len(surface.strip()) <= 128))):
        raise ValueError("Incomplete or invalid side-range capture provenance")
    if "request_elapsed_ms" in line and (
        type(elapsed) not in (int, float) or not 0 <= elapsed <= 350
        or age_ms + elapsed > 350
    ):
        raise ValueError("Invalid side-range capture provenance or transport age")
    return {
        "firmware_commit": firmware.strip(), "mount_id": mount.strip(),
        "surface_condition": surface.strip() if surface is not None else None,
        "request_age_recorded": "request_elapsed_ms" in line,
    }


def analyze(rows: list[dict], robot_id: str) -> dict:
    samples = defaultdict(list)
    seen_capture_ids = defaultdict(set)
    # WROOM /status reports each lens's actual conversion millisecond and
    # one boot epoch. A fresh operator sample_id alone is not a fresh ToF
    # measurement: repeated HTTP reads may still show the same conversion.
    last_conversion_ms: dict[str, int] = {}
    measured_boot_id: int | None = None
    measured_provenance: dict | None = None
    for index, line in enumerate(rows):
        if (not isinstance(line, dict) or line.get("robot_id") != robot_id
                or type(line.get("direction")) is not str
                or line.get("direction") not in SIDE
                or type(line.get("label")) is not str
                or line.get("label") not in {"near", "far"}):
            raise ValueError("Labeled robot identity, side and near/far required")
        channel = SIDE[line["direction"]]
        data = line.get("side_ranges")
        if not isinstance(data, dict):
            raise ValueError("Actual WROOM side_ranges required")
        mm, age = data.get("mm"), data.get("age_ms")
        stamps, boot_id = data.get("sample_ms"), data.get("boot_id")
        valid, present = data.get("valid_mask"), data.get("present_mask")
        if (not isinstance(mm, list) or len(mm) != 3
                or not isinstance(age, list) or len(age) != 3
                or type(valid) is not int or type(present) is not int
                or not 0 <= valid <= 7 or not 0 <= present <= 7
                or (valid & ~present) or not valid & (1 << channel)
                or data.get("motion_certified") is not False
                or type(mm[channel]) is not int
                or not 30 <= mm[channel] <= 1300
                or type(age[channel]) is not int
                or not 0 <= age[channel] <= 350
                or not isinstance(stamps, list) or len(stamps) != 3
                or type(stamps[channel]) is not int
                or not 0 <= stamps[channel] <= 0xffffffff
                or type(boot_id) is not int
                or not 1 <= boot_id <= 0xffffffff):
            raise ValueError("Invalid, stale, absent or forged real side sample")
        provenance = _capture_provenance(line, age[channel])
        if index == 0:
            measured_provenance = provenance
        elif provenance != measured_provenance:
            raise ValueError("Cannot mix side-range capture provenance in one calibration")
        # A repeated GET /status is NOT an independently measured conversion.
        # Require a physical record ID (monotonic camera/logger capture number)
        # assigned by the measurement capture utility, not by this analyzer.
        capture_id = line.get("sample_id")
        if (type(capture_id) is not int or capture_id < 1
                or capture_id in seen_capture_ids[line["direction"]]):
            # One physical side-lens conversion cannot be both near and far.
            # Separate lenses may share one synchronized sweep/capture ID.
            raise ValueError("Unique positive measured sample_id required per side direction")
        direction = line["direction"]
        if measured_boot_id is not None and boot_id != measured_boot_id:
            raise ValueError("Cannot mix WROOM boot identities in one side-range calibration")
        observed_ms = stamps[channel]
        previous_ms = last_conversion_ms.get(direction)
        if previous_ms is not None:
            # Subtraction modulo uint32 permits a genuine millis rollover,
            # but rejects equal conversions and old frames replayed afterward.
            advance = (observed_ms - previous_ms) & 0xffffffff
            if not 0 < advance < 0x80000000:
                raise ValueError("Repeated or reversed physical side-range conversion")
        measured_boot_id = boot_id
        last_conversion_ms[direction] = observed_ms
        seen_capture_ids[direction].add(capture_id)
        samples[direction, line["label"]].append((capture_id, mm[channel]))

    summary = {}
    for side in SIDE:
        near = [mm for _, mm in samples[side, "near"]]
        far = [mm for _, mm in samples[side, "far"]]
        if len(near) < 20 or len(far) < 20:
            raise ValueError(f"Need >=20 independent near and far {side} trials")
        q95_near = percentile(near, 0.95)
        q05_far = percentile(far, 0.05)
        summary[side] = {
            "near_trials": len(near), "far_trials": len(far),
            "near_p95_mm": q95_near, "far_p05_mm": q05_far,
        }

    # Conservative shared threshold across all three independently labeled
    # lens geometries, with 20 mm of reserve on both sides. If the near and
    # far clouds overlap, the fitter refuses to produce a fake calibration.
    low = max(35, max(percentile(
        [mm for _, mm in samples[side, "near"]], .95
    ) for side in SIDE) + 20)
    high = min(1000, min(percentile(
        [mm for _, mm in samples[side, "far"]], .05
    ) for side in SIDE) - 20)
    # Runtime rearms only at threshold + 60 mm or farther. Bound the
    # candidate before choosing its midpoint so a feasible lower threshold
    # is not rejected. At most floor(n/20) far trials may miss this boundary.
    for side in SIDE:
        far = sorted(mm for _, mm in samples[side, "far"])
        high = min(high, far[len(far) // 20] - 60)
    if low > high:
        raise ValueError("Near/far distributions overlap or exceed policy limits")
    proposed = (low + high) // 2
    # A strict 95% measured classification check for each independent side.
    if any(
        sum(value <= proposed for _, value in samples[side, "near"]) / len(samples[side, "near"]) < .95
        or sum(value >= proposed + 60 for _, value in samples[side, "far"]) / len(samples[side, "far"]) < .95
        for side in SIDE
    ):
        raise ValueError("Unable to meet 95% per-side near/far separation")
    return {
        "robot_id": robot_id,
        "suggested_side_near_threshold_mm": proposed,
        "directions": summary,
        "samples_total": sum(len(x) for x in samples.values()),
        "capture_provenance": measured_provenance,
        "physical_acceptance_pass": False,
        "independent_sample_provenance_verified": False,
        "human_review_required": True,
        "no_motion_authority": True,
        "note": "Record IDs are operator supplied; inspect real oscilloscope/serial timestamps before opting in.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--robot", required=True)
    parser.add_argument("--input", required=True, type=Path)
    args = parser.parse_args()
    rows = load_trial_rows(args.input)
    print(json.dumps(analyze(rows, args.robot), indent=2))


if __name__ == "__main__":
    main()
