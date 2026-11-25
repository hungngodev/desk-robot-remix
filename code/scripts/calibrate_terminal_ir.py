"""Collect and evaluate actual left/center/right dual IR beacon field readings.

Read-only Mac endpoint. It NEVER starts terminal docking, motors, or charging.
The human positions the UNPOWERED robot and the low voltage 38kHz beacon.
This is a candidate signal diagnostic, not geometric bearing calibration.
"""
from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import math
import os
import re
import stat
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from desk_robot.dock_ir import dock_beacon_code, validate_ir

POSITION_LABELS = ("left", "center", "right")
REFLECTION_LABEL = "reflection_only"
LABELS = (*POSITION_LABELS, REFLECTION_LABEL)

_ROBOT_ID = re.compile(r"[A-Za-z0-9_-]{1,40}\Z")


def _safe_ir_origin(base_url: str, robot_id: str) -> str:
    """Reject unsafe destinations before attaching a live operator token."""
    if type(robot_id) is not str or not _ROBOT_ID.fullmatch(robot_id):
        raise ValueError("Require exact configured robot identity")
    if (type(base_url) is not str or base_url != base_url.strip()
            or any(ord(ch) < 32 for ch in base_url)):
        raise ValueError("Invalid terminal IR capture API origin")
    try:
        parsed = urlsplit(base_url)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid terminal IR capture API origin") from exc
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError("Invalid terminal IR capture API origin")
    if parsed.scheme == "http":
        try:
            loopback = (parsed.hostname == "localhost"
                        or ipaddress.ip_address(parsed.hostname).is_loopback)
        except ValueError:
            loopback = False
        if not loopback:
            raise ValueError("Bearer token requires loopback HTTP or HTTPS")
    return base_url.rstrip("/")


def _private_trial_parent_fd(parent: Path) -> int:
    """Create private descendants through verified directory handles."""
    absolute = parent.absolute()
    if ".." in absolute.parts or parent.is_symlink():
        raise ValueError("Unsafe terminal IR trial directory alias or traversal")
    descriptor = os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for name in absolute.parts[1:]:
            owner = os.fstat(descriptor)
            try:
                entry = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            except FileNotFoundError:
                os.mkdir(name, mode=0o700, dir_fd=descriptor)
                entry = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if stat.S_ISLNK(entry.st_mode):
                # macOS /var is a root-owned alias under a root-owned parent.
                if (entry.st_uid != 0 or owner.st_uid != 0
                        or stat.S_IMODE(owner.st_mode) & 0o022):
                    raise ValueError("Unsafe terminal IR trial directory alias")
            elif not stat.S_ISDIR(entry.st_mode):
                raise ValueError("Terminal IR trial parent is not a directory")
            flags = os.O_RDONLY | os.O_DIRECTORY
            if not stat.S_ISLNK(entry.st_mode):
                flags |= os.O_NOFOLLOW
            next_descriptor = os.open(name, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        leaf = os.fstat(descriptor)
        if (leaf.st_uid != os.geteuid()
                or stat.S_IMODE(leaf.st_mode) & 0o077):
            raise ValueError(
                "Terminal IR trial directory must be owned and private mode 0700"
            )
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def append_trial_rows(path: Path, rows: list[dict]) -> None:
    """Append captured JSONL only to one owned private regular file."""
    descriptor = _private_trial_parent_fd(path.parent)
    try:
        # NONBLOCK prevents a substituted FIFO from hanging the capture tool.
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK
        file_descriptor = os.open(path.name, flags, 0o600, dir_fd=descriptor)
        try:
            target = os.fstat(file_descriptor)
            if (not stat.S_ISREG(target.st_mode)
                    or target.st_uid != os.geteuid()
                    or target.st_nlink != 1
                    or stat.S_IMODE(target.st_mode) & 0o077):
                raise ValueError(
                    "Terminal IR trial output must be an owned private regular file"
                )
            with os.fdopen(file_descriptor, "a", encoding="utf-8") as output:
                file_descriptor = -1
                for row in rows:
                    output.write(json.dumps(row, separators=(",", ":")) + "\n")
        finally:
            if file_descriptor >= 0:
                os.close(file_descriptor)
    finally:
        os.close(descriptor)



def _unique_trial_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject ambiguous labels, timestamps and nested optical receiver facts."""
    fields: dict[str, object] = {}
    for key, value in pairs:
        if key in fields:
            raise ValueError("Duplicate terminal IR trial JSON field: " + key)
        fields[key] = value
    return fields


def _reject_nonfinite_trial_json(token: str) -> None:
    raise ValueError("Nonfinite terminal IR trial JSON constant: " + token)


def load_trial_rows(path: Path) -> list[dict]:
    """Parse physical trial JSONL without silently overwriting evidence."""
    return [
        json.loads(
            line, object_pairs_hook=_unique_trial_fields,
            parse_constant=_reject_nonfinite_trial_json,
        )
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def analyze(rows: list[dict], robot_id: str, *, min_per_position: int = 20,
            expected_dock_id: int | None = None) -> dict:
    if not robot_id or not 10 <= min_per_position <= 500:
        raise ValueError("Invalid robot ID or minimum real sample count")
    data: dict[str, list[dict]] = {name: [] for name in POSITION_LABELS}
    reflection_valid: list[bool] = []
    previous: tuple[int, int] | None = None
    last_at = -1.0
    observed_dock_code: int | None = None
    if expected_dock_id is not None:
        observed_dock_code = dock_beacon_code(expected_dock_id)
    for row in rows:
        if not isinstance(row, dict) or row.get("label") not in LABELS:
            raise ValueError("Explicitly labeled left/center/right records required")
        reading = validate_ir(row.get("ir"), robot_id,
                              expected_dock_id=expected_dock_id)
        if reading["match"] and reading["code"] != 0:
            if observed_dock_code is None:
                observed_dock_code = reading["code"]
            elif reading["code"] != observed_dock_code:
                raise ValueError(
                    "Mixed NEC dock beacons in trial: observations must share one assigned dock"
                )
        stamp = row.get("received_monotonic")
        try:
            valid_stamp = (
                type(stamp) in (int, float) and math.isfinite(stamp)
                and 0 <= stamp and stamp > last_at
            )
        except OverflowError:
            # JSON integers are unbounded; malformed clocks must fail closed.
            valid_stamp = False
        if not valid_stamp:
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
        if row["label"] == REFLECTION_LABEL:
            # Any decoded signal with the direct path blocked is ambiguous,
            # even if only one side sees it or its sequence is cached.
            reflection_valid.append(reading["left_valid"] or reading["right_valid"])
            continue
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
    assigned_dock = (
        expected_dock_id
        if expected_dock_id is not None
        else (
            next(
                (i for i in range(1, 6) if dock_beacon_code(i) == observed_dock_code),
                None,
            )
            if observed_dock_code is not None
            else None
        )
    )
    return {
        "robot_id": robot_id,
        "assigned_dock_id": assigned_dock,
        "dock_id_assigned": expected_dock_id is not None,
        "positions": summary,
        "observations_total": len(rows),
        "independent_fresh_minimum_met": enough_fresh,
        "candidate_differential_signal": separates,
        "reflection_control_records": len(reflection_valid),
        "reflection_control_valid_records": sum(reflection_valid),
        "candidate_reflection_control_clear": (
            separates and len(reflection_valid) >= min_per_position
            and not any(reflection_valid)
        ),
        "multipath_rejection_physically_verified": False,
        "requires_human_optical_baffle_and_receiver_trial": True,
        "absolute_bearing_calibrated": False,
        "motor_authorized": False,
        "charging_authorized": False,
        "physical_acceptance_pass": False,
        "note": (
            "Receiver bias is an observed signal rate, not an angle or distance. "
            "Reflection-only labels require human confirmation that the direct "
            "path was blocked with the beacon active. Measure drift, baffle "
            "geometry and last-centimeter stopping separately."
        ),
    }


async def capture(base_url: str, token: str, robot_id: str,
                  label: str, count: int, interval_s: float,
                  expected_dock_id: int | None = None) -> list[dict]:
    if (label not in LABELS or not 20 <= count <= 500
            or not .05 <= interval_s <= 2
            or not token or len(token) < 24):
        raise ValueError("A labeled read-only authenticated trial is required")
    origin = _safe_ir_origin(base_url, robot_id)
    rows = []
    async with httpx.AsyncClient(
        base_url=origin,
        headers={"Authorization": f"Bearer {token}"},
        timeout=httpx.Timeout(4, connect=1),
        follow_redirects=False,
    ) as client:
        for i in range(count):
            # Optical age is measured at the head, before HTTP delivery.
            # Count that delivery time rather than promoting stale frames.
            request_started = time.monotonic()
            response = await client.get(f"/v1/robots/{robot_id}/dock/ir")
            received_at = time.monotonic()
            response.raise_for_status()
            # Apply the same strict parser as saved JSONL before validating
            # live evidence: duplicate fields must not overwrite prior facts.
            payload = response.json(
                object_pairs_hook=_unique_trial_fields,
                parse_constant=_reject_nonfinite_trial_json,
            )
            reading = validate_ir(payload, robot_id, expected_dock_id=expected_dock_id)
            roundtrip_ms = (received_at - request_started) * 1000.0
            if (not math.isfinite(roundtrip_ms) or roundtrip_ms < 0
                    or any(
                        reading[f"{side}_valid"]
                        and reading[f"{side}_age_ms"] + roundtrip_ms > 200
                        for side in ("left", "right")
                    )):
                raise ValueError(
                    "Delayed terminal IR HTTP response exceeds optical freshness budget"
                )
            rows.append({
                "label": label, "received_monotonic": received_at,
                "ir": reading,
            })
            if i + 1 != count:
                await asyncio.sleep(interval_s)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--robot", required=True)
    parser.add_argument("--dock-id", type=int, choices=range(1, 6),
                        help="Required actual physical beacon ID 1 through 5")
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
    if args.dock_id is None:
        parser.error("Terminal IR calibration requires --dock-id 1 through 5")
    if args.input:
        rows = load_trial_rows(args.input)
        print(json.dumps(analyze(
            rows, args.robot, expected_dock_id=args.dock_id,
        ), indent=2))
        return
    if not args.out or args.label is None:
        parser.error("Supply --input for analysis or --out and --label for real capture")
    # The user must move an UNPOWERED robot to three stationary positions.
    # No motion, camera, battery or charging endpoint is ever requested.
    rows = asyncio.run(capture(
        args.api, os.environ.get(args.token_env, ""), args.robot,
        args.label, args.samples, args.interval, args.dock_id,
    ))
    append_trial_rows(args.out, rows)
    print(json.dumps({
        "label": args.label, "records_written": len(rows),
        "output": str(args.out), "physical_acceptance_pass": False,
        "motor_authorized": False, "charging_authorized": False,
    }, indent=2))


if __name__ == "__main__":
    main()
