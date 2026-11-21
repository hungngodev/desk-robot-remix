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


def percentile(values: list[int], proportion: float) -> int:
    if not values or not 0 <= proportion <= 1:
        raise ValueError("Missing samples or invalid percentile")
    sorted_values = sorted(values)
    # Conservative nearest rank, rather than interpolating fake mm samples.
    index = math.ceil(proportion * len(values)) - 1
    return sorted_values[max(0, min(len(sorted_values) - 1, index))]


def analyze(rows: list[dict], robot_id: str) -> dict:
    samples = defaultdict(list)
    seen_capture_ids = defaultdict(set)
    for line in rows:
        if (not isinstance(line, dict) or line.get("robot_id") != robot_id
                or line.get("direction") not in SIDE
                or line.get("label") not in {"near", "far"}):
            raise ValueError("Labeled robot identity, side and near/far required")
        channel = SIDE[line["direction"]]
        data = line.get("side_ranges")
        if not isinstance(data, dict):
            raise ValueError("Actual WROOM side_ranges required")
        mm, age = data.get("mm"), data.get("age_ms")
        valid, present = data.get("valid_mask"), data.get("present_mask")
        if (not isinstance(mm, list) or len(mm) != 3
                or not isinstance(age, list) or len(age) != 3
                or type(valid) is not int or type(present) is not int
                or not 0 <= valid <= 7 or not 0 <= present <= 7
                or (valid & ~present) or not valid & (1 << channel)
                or data.get("motion_certified") is not False
                or type(mm[channel]) is not int
                or not 1 <= mm[channel] <= 1300
                or type(age[channel]) is not int
                or not 0 <= age[channel] <= 350):
            raise ValueError("Invalid, stale, absent or forged real side sample")
        # A repeated GET /status is NOT an independently measured conversion.
        # Require a physical record ID (monotonic camera/logger capture number)
        # assigned by the measurement capture utility, not by this analyzer.
        capture_id = line.get("sample_id")
        if (type(capture_id) is not int or capture_id < 1
                or capture_id in seen_capture_ids[line["direction"]]):
            # One physical side-lens conversion cannot be both near and far.
            # Separate lenses may share one synchronized sweep/capture ID.
            raise ValueError("Unique positive measured sample_id required per side direction")
        seen_capture_ids[line["direction"]].add(capture_id)
        samples[line["direction"], line["label"]].append(
            (capture_id, mm[channel])
        )

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
    if low > high:
        raise ValueError("Near/far distributions overlap or exceed policy limits")
    proposed = (low + high) // 2
    # A strict 95% measured classification check for each independent side.
    if any(
        sum(value <= proposed for _, value in samples[side, "near"]) / len(samples[side, "near"]) < .95
        or sum(value > proposed + 60 for _, value in samples[side, "far"]) / len(samples[side, "far"]) < .95
        for side in SIDE
    ):
        raise ValueError("Unable to meet 95% per-side near/far separation")
    return {
        "robot_id": robot_id,
        "suggested_side_near_threshold_mm": proposed,
        "directions": summary,
        "samples_total": sum(len(x) for x in samples.values()),
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
    rows = []
    for line in args.input.read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line))
    print(json.dumps(analyze(rows, args.robot), indent=2))


if __name__ == "__main__":
    main()
