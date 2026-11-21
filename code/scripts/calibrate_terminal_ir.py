"""Collect and evaluate actual left/center/right dual IR beacon field readings.

Read-only Mac endpoint. It NEVER starts terminal docking, motors, or charging.
The human positions the UNPOWERED robot and the low voltage 38kHz beacon.
This is a candidate signal diagnostic, not geometric bearing calibration.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import time
from pathlib import Path

import httpx
from desk_robot.dock_ir import validate_ir

LABELS = ("left", "center", "right")


def analyze(rows: list[dict], robot_id: str, *, min_per_position: int = 20,
            expected_dock_id: int | None = None) -> dict:
    if not robot_id or not 10 <= min_per_position <= 500:
        raise ValueError("Invalid robot ID or minimum real sample count")
    data: dict[str, list[dict]] = {name: [] for name in LABELS}
    previous: tuple[int, int] | None = None
    last_at = -1.0
    for row in rows:
        if not isinstance(row, dict) or row.get("label") not in LABELS:
            raise ValueError("Explicitly labeled left/center/right records required")
        reading = validate_ir(row.get("ir"), robot_id,
                              expected_dock_id=expected_dock_id)
        stamp = row.get("received_monotonic")
        if type(stamp) not in (int, float) or not math.isfinite(stamp) or stamp <= last_at:
            raise ValueError("Strictly increasing recorded receive timestamps required")
        last_at = stamp
        sequences = (reading["left_seq"], reading["right_seq"])
        if previous is None:
            advances = (sequences[0] > 0, sequences[1] > 0)
        else:
            # Independent RMT receiver counters are not a pairwise clock.
            # One side advancing cannot refresh the other cached side.
            # Modulo arithmetic permits true unsigned 32-bit counter wrap.
            deltas = tuple(
                (after - before) & 0xffffffff
                for after, before in zip(sequences, previous, strict=True)
            )
            if any(delta >= 0x80000000 for delta in deltas):
                raise ValueError("Reboot or out-of-order receiver sequences: restart trial")
            advances = tuple(delta > 0 for delta in deltas)
            if not any(advances) and any(
                reading[f"{side}_valid"] for side in ("left", "right")
            ):
                raise ValueError("Replayed receiver counter with claimed new optical evidence")
        previous = sequences
        left_new = reading["left_valid"] and advances[0]
        right_new = reading["right_valid"] and advances[1]
        data[row["label"]].append({
            "left_new": left_new,
            "right_new": right_new,
            "pair_new": left_new and right_new and reading["match"],
        })
    if any(len(samples) < min_per_position for samples in data.values()):
        raise ValueError("Need independently labeled real observations for all 3 positions")
    summary = {}
    for label, readings in data.items():
        length = len(readings)
        left_fresh = sum(x["left_new"] for x in readings)
        right_fresh = sum(x["right_new"] for x in readings)
        pair_fresh = sum(x["pair_new"] for x in readings)
        summary[label] = {
            "records": length,
            "left_fresh_count": left_fresh,
            "right_fresh_count": right_fresh,
            "both_matching_count": pair_fresh,
            "left_fresh_fraction": round(left_fresh / length, 3),
            "right_fresh_fraction": round(right_fresh / length, 3),
            "both_matching_fraction": round(pair_fresh / length, 3),
        }
    left = summary["left"]
    center = summary["center"]
    right = summary["right"]
    # The minimum is independent optical acquisitions, not HTTP polls.
    enough_fresh = (
        left["left_fresh_count"] >= min_per_position
        and center["both_matching_count"] >= min_per_position
        and right["right_fresh_count"] >= min_per_position
    )
    separates = (
        enough_fresh
        and left["left_fresh_fraction"] > left["right_fresh_fraction"] + .25
        and right["right_fresh_fraction"] > right["left_fresh_fraction"] + .25
        and center["both_matching_fraction"] >= .50
        and center["left_fresh_fraction"] >= .50
        and center["right_fresh_fraction"] >= .50
    )
    return {
        "robot_id": robot_id, "positions": summary,
        "observations_total": len(rows),
        "independent_fresh_minimum_met": enough_fresh,
        "candidate_differential_signal": separates,
        "requires_human_optical_baffle_and_receiver_trial": True,
        "absolute_bearing_calibrated": False,
        "motor_authorized": False,
        "charging_authorized": False,
        "physical_acceptance_pass": False,
        "note": (
            "Receiver bias is an observed signal rate, not an angle or distance. "
            "Measure drift, baffle geometry and last-centimeter stopping separately."
        ),
    }


async def capture(base_url: str, token: str, robot_id: str,
                  label: str, count: int, interval_s: float,
                  expected_dock_id: int | None = None) -> list[dict]:
    if (label not in LABELS or not 20 <= count <= 500
            or not .05 <= interval_s <= 2
            or not token or len(token) < 24):
        raise ValueError("A labeled read-only authenticated trial is required")
    rows = []
    async with httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        headers={"Authorization": f"Bearer {token}"},
        timeout=httpx.Timeout(4, connect=1),
        follow_redirects=False,
    ) as client:
        for i in range(count):
            response = await client.get(f"/v1/robots/{robot_id}/dock/ir")
            response.raise_for_status()
            reading = validate_ir(response.json(), robot_id,
                                  expected_dock_id=expected_dock_id)
            rows.append({
                "label": label, "received_monotonic": time.monotonic(),
                "ir": reading,
            })
            if i + 1 != count:
                await asyncio.sleep(interval_s)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--robot", required=True)
    parser.add_argument("--dock-id", type=int, choices=range(1, 6),
                        help="Required actual physical beacon ID 1 through 5 for live capture")
    parser.add_argument("--input", type=Path, help="Read previously labeled JSONL")
    parser.add_argument("--out", type=Path, help="Append new labeled JSONL evidence")
    parser.add_argument("--label", choices=LABELS)
    parser.add_argument("--api", default="http://127.0.0.1:8765")
    parser.add_argument("--token-env", default="DESK_ROBOT_OPERATOR_TOKEN")
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--interval", type=float, default=.25)
    args = parser.parse_args()
    if args.input and (args.out or args.label):
        parser.error("--input cannot be combined with --out or --label")
    if args.input:
        rows = [json.loads(line) for line in args.input.read_text().splitlines()
                if line.strip()]
        print(json.dumps(analyze(
            rows, args.robot, expected_dock_id=args.dock_id,
        ), indent=2))
        return
    if not args.out or args.label is None:
        parser.error("Supply --input for analysis or --out and --label for real capture")
    if args.dock_id is None:
        parser.error("Live optical calibration requires --dock-id 1 through 5")
    # The user must move an UNPOWERED robot to three stationary positions.
    # No motion, camera, battery or charging endpoint is ever requested.
    rows = asyncio.run(capture(
        args.api, os.environ.get(args.token_env, ""), args.robot,
        args.label, args.samples, args.interval, args.dock_id,
    ))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("a", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, separators=(",", ":")) + "\n")
    print(json.dumps({
        "label": args.label, "records_written": len(rows),
        "output": str(args.out), "physical_acceptance_pass": False,
        "motor_authorized": False, "charging_authorized": False,
    }, indent=2))


if __name__ == "__main__":
    main()
