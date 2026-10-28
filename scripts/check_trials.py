"""Summarize human-recorded physical trials; never imports simulated results."""

import argparse
import csv
import json
from pathlib import Path


def summarize(rows, robot_id):
    result = {}
    for category in ("key", "candy"):
        selected = [r for r in rows if r["robot_id"] == robot_id and r["category"] == category]
        ids = [int(r["trial"]) for r in selected]
        if len(ids) != len(set(ids)) or any(i < 1 or i > 10 for i in ids):
            raise ValueError("Each category needs distinct trial numbers 1..10")
        successes = 0
        for r in selected:
            if (
                not all(r[k] for k in ("object_description", "date", "firmware", "calibration"))
                or float(r["mass_g"]) <= 0
            ):
                raise ValueError(
                    "Record real object, mass, date and configuration for every attempt"
                )
            successes += (
                float(r["lift_mm"]) >= 10
                and float(r["hold_seconds"]) >= 3
                and r["placed_under_control"] == "true"
                and r["assisted"] == "false"
                and (category != "key" or r["flat_start"] == "true")
            )
        result[category] = {
            "attempts": len(selected),
            "successes": successes,
            "passed": len(selected) == 10 and successes >= 8,
        }
    return {
        "robot_id": robot_id,
        "categories": result,
        "physical_acceptance_pass": all(r["passed"] for r in result.values()),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--file",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "test-results/physical-trials.csv",
    )
    p.add_argument("--robot", default="robot-01")
    p.add_argument("--require-pass", action="store_true")
    args = p.parse_args()
    with args.file.open() as stream:
        result = summarize(list(csv.DictReader(stream)), args.robot)
    print(json.dumps(result, indent=2))
    if args.require_pass and not result["physical_acceptance_pass"]:
        p.exit(1, "Physical trial target has not been met.\n")
