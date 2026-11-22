"""Summarize human-recorded physical trials; never imports simulated results."""

import argparse
import csv
import json
import math
from datetime import date
from pathlib import Path


def _finite_measurement(row, field, *, positive=False):
    """A physical measurement is never infinity, NaN, or a negative distance."""
    try:
        value = float(row[field])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"Invalid physical measurement: {field}") from exc
    if not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError(f"Invalid physical measurement: {field}")
    return value


def summarize(rows, robot_id):
    result = {}
    # A5 is one acceptance run for one fitted robot, not an average of
    # attempts from different firmware images or jaw calibrations.
    accepted_setup = None
    for category in ("key", "candy"):
        selected = [r for r in rows if r["robot_id"] == robot_id and r["category"] == category]
        ids = [int(r["trial"]) for r in selected]
        if len(ids) != len(set(ids)) or any(i < 1 or i > 10 for i in ids):
            raise ValueError("Each category needs distinct trial numbers 1..10")
        successes = 0
        for r in selected:
            if not all(
                isinstance(r.get(k), str) and r[k].strip()
                for k in ("object_description", "date", "firmware", "calibration")
            ):
                raise ValueError("Record real object, mass, date and configuration for every attempt")
            try:
                trial_date = date.fromisoformat(r["date"])
            except ValueError as exc:
                raise ValueError("Invalid physical trial date") from exc
            if trial_date.isoformat() != r["date"]:
                raise ValueError("Invalid physical trial date")
            # A future-dated record cannot prove a completed physical trial.
            if trial_date > date.today():
                raise ValueError("Future physical trial date")
            setup = (r["firmware"].strip(), r["calibration"].strip())
            if accepted_setup is None:
                accepted_setup = setup
            elif setup != accepted_setup:
                raise ValueError("A5 trials must use the same firmware and calibration")
            _finite_measurement(r, "mass_g", positive=True)
            lift_mm = _finite_measurement(r, "lift_mm")
            hold_seconds = _finite_measurement(r, "hold_seconds")
            successes += (
                lift_mm >= 10
                and hold_seconds >= 3
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
        default=Path(__file__).resolve().parents[2] / "docs/records/physical-trials.csv",
    )
    p.add_argument("--robot", default="robot-01")
    p.add_argument("--require-pass", action="store_true")
    args = p.parse_args()
    with args.file.open(newline="") as stream:
        reader = csv.DictReader(stream)
        headers = reader.fieldnames
        # DictReader silently overwrites earlier values for repeated names.
        # Contradictory assisted/configuration fields must never pass A5.
        if (not headers or any(not name or name != name.strip()
                               for name in headers)
                or len(headers) != len(set(headers))):
            raise ValueError("A5 physical trial CSV needs unique, nonempty column names")
        result = summarize(list(reader), args.robot)
    print(json.dumps(result, indent=2))
    if args.require_pass and not result["physical_acceptance_pass"]:
        p.exit(1, "Physical trial target has not been met.\n")
