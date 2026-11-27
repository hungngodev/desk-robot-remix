"""Summarize human-recorded physical trials; never imports simulated results."""

import argparse
import csv
import hashlib
import json
import math
import re
from datetime import date
from pathlib import Path

# Bounded A5 object/mechanism envelope derived from docs/guides/first-gripper-test.md,
# docs/records/verification.md (>=10 mm lift, >=3 s hold of flat key / wrapped candy),
# and docs/cad/originals/forklift (fork_lift_e 11.8 mm / fork_lift_f 14.3 mm geometry
# driven by MG90S micro servo). Reject absurd finite out-of-envelope claims.
MAX_A5_MASS_G = 250.0
MAX_A5_LIFT_MM = 150.0
MAX_A5_HOLD_SECONDS = 300.0

_PLACEHOLDER_LABELS = frozenset({
    "test", "testing", "synthetic", "fixture", "placeholder", "example",
    "sample", "unknown", "tbd", "n/a", "na", "dummy", "reviewer", "operator",
    "bench-profile", "verified-test-image",
})
_PLACEHOLDER_PATTERNS = (
    "unit test", "test fixture", "not a real", "synthetic", "placeholder",
)


def _finite_measurement(row, field, *, positive=False, max_value=None):
    """A physical measurement is finite, nonnegative, and within protocol bounds."""
    try:
        raw = row[field]
        if isinstance(raw, bool):
            raise ValueError("Boolean is not a physical measurement")
        value = float(raw)
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"Invalid physical measurement: {field}") from exc
    if not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError(f"Invalid physical measurement: {field}")
    if max_value is not None and value > max_value:
        raise ValueError(f"Out-of-envelope physical measurement: {field}")
    return value


def _is_placeholder_label(value: str) -> bool:
    norm = " ".join(value.strip().casefold().split())
    if norm in _PLACEHOLDER_LABELS:
        return True
    return any(pattern in norm for pattern in _PLACEHOLDER_PATTERNS)


def _finite_json_float(raw: str) -> float:
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError("Nonfinite A5 run manifest number")
    return value


def _validate_run_manifest(
    manifest: dict,
    *,
    robot_id: str,
    assembly_id: str,
    firmware: str,
    calibration: str,
    csv_sha256: str | None = None,
) -> dict:
    """Bind scored CSV trials to an immutable commit, calibration, and reviewer record."""
    if not isinstance(manifest, dict):
        raise ValueError("Invalid A5 run manifest")
    required = (
        "run_id", "commit_sha", "robot_id", "assembly_id", "firmware",
        "calibration", "calibration_sha", "objective_evidence_path",
        "reviewer", "acceptance_state",
    )
    missing = [key for key in required if not isinstance(manifest.get(key), str)
               or not manifest[key].strip()]
    if missing:
        raise ValueError(f"Incomplete A5 run manifest fields: {', '.join(missing)}")
    for key in ("commit_sha", "calibration_sha"):
        sha = manifest[key].strip()
        if re.fullmatch(r"[0-9a-f]{40}", sha) is None:
            raise ValueError(f"A5 run manifest {key} must be a 40-char git hex SHA")
    expected_ids = {
        "robot_id": robot_id,
        "assembly_id": assembly_id,
        "firmware": firmware,
        "calibration": calibration,
    }
    for key, expected in expected_ids.items():
        if manifest[key].strip() != expected:
            raise ValueError(f"A5 run manifest {key} disagrees with trial CSV")
        if _is_placeholder_label(manifest[key]):
            raise ValueError(f"A5 run manifest {key} uses a placeholder identity")
    if _is_placeholder_label(manifest["reviewer"]):
        raise ValueError("A5 run manifest requires a real named reviewer")
    if manifest["acceptance_state"].strip() != "bench_passed":
        raise ValueError("A5 run manifest acceptance_state is not bench_passed")
    if csv_sha256 is not None:
        recorded_csv_sha = manifest.get("trials_csv_sha256")
        if not isinstance(recorded_csv_sha, str) or recorded_csv_sha.strip() != csv_sha256:
            raise ValueError("A5 run manifest trials_csv_sha256 disagrees with trial CSV")
    return {
        "run_id": manifest["run_id"].strip(),
        "commit_sha": manifest["commit_sha"].strip(),
        "calibration_sha": manifest["calibration_sha"].strip(),
        "reviewer": manifest["reviewer"].strip(),
        "objective_evidence_path": manifest["objective_evidence_path"].strip(),
        "acceptance_state": manifest["acceptance_state"].strip(),
    }


def summarize(rows, robot_id, *, run_manifest=None, csv_sha256=None):
    # Match RobotConfig.id. A blank or misspelled source label must never
    # certify a physical gripper as a configured robot or silently discard
    # a failed attempt from that robot's population.
    def valid_robot_id(value: object) -> bool:
        return (
            type(value) is str
            and re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", value) is not None
        )
    if not valid_robot_id(robot_id) or any(
        not valid_robot_id(row.get("robot_id")) for row in rows
    ):
        raise ValueError("Invalid A5 trial robot identity")
    # Every recorded attempt for this robot belongs to an A5 population.
    # An unexpected category cannot silently vanish from the denominator.
    if any(r["robot_id"] == robot_id and r["category"] not in ("key", "candy")
           for r in rows):
        raise ValueError("Unrecognized physical trial category for selected robot")
    result = {}
    # A5 is one acceptance run for one fitted robot, not an average of
    # attempts from different firmware images or jaw calibrations.
    accepted_setup = None
    placeholder_fields = set()
    # Same configured ID can survive a chassis, gripper or power rebuild.
    # A5 counts a single fitted physical assembly, not mixed hardware trials.
    for category in ("key", "candy"):
        selected = [r for r in rows if r["robot_id"] == robot_id and r["category"] == category]
        # CSV evidence names exactly ten attempts. Python int() silently
        # accepts "0_1", "01", whitespace, booleans and fractional numeric
        # values; none are an unambiguous physical trial label.
        if any(
            type(r.get("trial")) is not str
            or re.fullmatch(r"(?:10|[1-9])", r["trial"]) is None
            for r in selected
        ):
            raise ValueError("Each category needs canonical trial numbers 1..10")
        ids = [int(r["trial"]) for r in selected]
        if len(ids) != len(set(ids)) or any(i < 1 or i > 10 for i in ids):
            raise ValueError("Each category needs distinct trial numbers 1..10")
        successes = 0
        for r in selected:
            if not all(
                isinstance(r.get(k), str) and r[k].strip()
                for k in ("object_description", "date", "firmware", "calibration")
            ):
                raise ValueError(
                    "Record real object, mass, date and configuration for every attempt"
                )
            for k in ("object_description", "firmware", "calibration", "assembly_id"):
                val = r.get(k)
                if isinstance(val, str) and _is_placeholder_label(val):
                    placeholder_fields.add(k)
            try:
                trial_date = date.fromisoformat(r["date"])
            except ValueError as exc:
                raise ValueError("Invalid physical trial date") from exc
            if trial_date.isoformat() != r["date"]:
                raise ValueError("Invalid physical trial date")
            # A future-dated record cannot prove a completed physical trial.
            if trial_date > date.today():
                raise ValueError("Future physical trial date")
            assembly_id = r.get("assembly_id")
            if (type(assembly_id) is not str or re.fullmatch(
                    r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", assembly_id) is None):
                raise ValueError("A5 trial requires a canonical physical assembly_id")
            setup = (r["firmware"].strip(), r["calibration"].strip(), assembly_id)
            if accepted_setup is None:
                accepted_setup = setup
            elif setup != accepted_setup:
                raise ValueError(
                    "A5 trials must use the same firmware and calibration and physical assembly"
                )
            # Each attempt, including an unsuccessful one, needs an actual
            # observation of assistance, placement and initial orientation.
            # Otherwise an unmeasured attempt could silently fill the 10-trial
            # denominator while eight measured successes certify the run.
            fields = ("placed_under_control", "assisted")
            if category == "key":
                fields += ("flat_start",)
            for field in fields:
                if r.get(field) not in ("true", "false"):
                    raise ValueError(f"Unmeasured A5 trial outcome: {field}")
            _finite_measurement(r, "mass_g", positive=True, max_value=MAX_A5_MASS_G)
            lift_mm = _finite_measurement(r, "lift_mm", max_value=MAX_A5_LIFT_MM)
            hold_seconds = _finite_measurement(
                r, "hold_seconds", max_value=MAX_A5_HOLD_SECONDS,
            )
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
    outcome_pass = all(r["passed"] for r in result.values())
    firmware = accepted_setup[0] if accepted_setup is not None else None
    calibration = accepted_setup[1] if accepted_setup is not None else None
    assembly_id = accepted_setup[2] if accepted_setup is not None else None

    manifest_summary = None
    manifest_verified = False
    if run_manifest is not None:
        if accepted_setup is None or not outcome_pass:
            raise ValueError("Cannot bind run manifest without a complete 10/10 passing setup")
        if placeholder_fields:
            raise ValueError(
                "A5 run manifest rejects placeholder CSV identities: "
                + ", ".join(sorted(placeholder_fields))
            )
        manifest_summary = _validate_run_manifest(
            run_manifest,
            robot_id=robot_id,
            assembly_id=assembly_id,
            firmware=firmware,
            calibration=calibration,
            csv_sha256=csv_sha256,
        )
        manifest_verified = True

    return {
        "robot_id": robot_id,
        "assembly_id": assembly_id,
        "firmware": firmware,
        "calibration": calibration,
        "categories": result,
        # Outcome score is distinct from manifest-backed qualification evidence.
        "outcome_score_only": not manifest_verified,
        "run_manifest_verified": manifest_verified,
        "run_manifest": manifest_summary,
        "placeholder_identities": sorted(placeholder_fields),
        "evidence_status": (
            "MANIFEST_VERIFIED_PENDING_SIGNOFF"
            if manifest_verified and outcome_pass and not placeholder_fields
            else "HOLD"
        ),
        # This tool validates human-supplied records; it cannot inspect a robot.
        "assembly_identity_physically_verified": False,
        "physical_acceptance_pass": outcome_pass,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--file",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "docs/records/physical-trials.csv",
    )
    p.add_argument("--robot", default="robot-01")
    p.add_argument("--run-manifest", type=Path, default=None)
    p.add_argument("--require-pass", action="store_true")
    p.add_argument("--require-manifest", action="store_true")
    args = p.parse_args()
    canonical = args.file.resolve() == p.get_default("file").resolve()
    raw_bytes = args.file.read_bytes()
    csv_digest = hashlib.sha256(raw_bytes).hexdigest()
    manifest_data = None
    if args.run_manifest is not None:
        from physical_trial_ledger import unique_object

        manifest_data = json.loads(
            args.run_manifest.read_text(encoding="utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=_finite_json_float,
            parse_float=_finite_json_float,
        )
    if args.require_manifest and manifest_data is None:
        raise ValueError("Qualified A5 evidence requires --run-manifest")
    with args.file.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream, strict=True)
        headers = reader.fieldnames
        # DictReader silently overwrites earlier values for repeated names.
        # Contradictory assisted/configuration fields must never pass A5.
        if (not headers or any(not name or name != name.strip()
                               for name in headers)
                or len(headers) != len(set(headers))):
            raise ValueError("A5 physical trial CSV needs unique, nonempty column names")
        rows = list(reader)
        if any(None in row or any(value is None for value in row.values())
               for row in rows):
            raise ValueError("A5 physical trial CSV row length differs from header")
        if canonical or manifest_data is not None:
            from physical_trial_ledger import validate_physical_rows

            validate_physical_rows(headers, rows)
        result = summarize(
            rows, args.robot,
            run_manifest=manifest_data, csv_sha256=csv_digest,
        )
    if canonical:
        if result["placeholder_identities"]:
            raise ValueError("Canonical physical trial contains placeholder identities")
        result["physical_trial_count"] = sum(row["robot_id"] == args.robot for row in rows)
    print(json.dumps(result, indent=2))
    if args.require_pass and not result["physical_acceptance_pass"]:
        p.exit(1, "Physical trial target has not been met.\n")
