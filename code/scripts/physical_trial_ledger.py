"""Validate the canonical A5 ledger without treating scores as bench signoff."""

import csv
import json
import re
from pathlib import Path

COLUMNS = (
    "robot_id", "assembly_id", "category", "trial", "object_description", "mass_g",
    "date", "firmware", "calibration", "flat_start", "lift_mm", "hold_seconds",
    "placed_under_control", "assisted", "notes",
)
NONPHYSICAL = re.compile(
    r"\b(?:simulated|simulation|simulator|synthetic|mock|test fixture|test image|"
    r"not (?:a )?(?:real|physical) trial)\b", re.IGNORECASE,
)


def validate_physical_rows(headers, rows):
    if tuple(headers or ()) != COLUMNS:
        raise ValueError("Canonical physical trial CSV schema mismatch")
    for row in rows:
        if set(row) != set(COLUMNS) or any(type(value) is not str for value in row.values()):
            raise ValueError("Malformed canonical physical trial row")
        fields = (
            "robot_id", "assembly_id", "object_description", "firmware", "calibration", "notes",
        )
        for field in fields:
            normalized = re.sub(r"[\W_]+", " ", row[field])
            if NONPHYSICAL.search(normalized):
                raise ValueError(f"Nonphysical trial provenance: {field}")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate physical summary key: {key}")
        result[key] = value
    return result


_ARCHIVE_METADATA = {
    "evidence_scope": "historical_snapshot",
    "current_head_verified": False,
}


def validate_canonical_ledger(root: Path, summarize):
    records = root / "docs/records"
    with (records / "physical-trials.csv").open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream, strict=True)
        rows = list(reader)
        validate_physical_rows(reader.fieldnames, rows)
    summary = json.loads(
        (records / "reports/physical-summary.json").read_text(encoding="utf-8"),
        object_pairs_hook=unique_object,
    )
    if type(summary) is not dict or summary.get("robot_id") != "robot-01":
        raise ValueError("Canonical physical summary must identify robot-01")
    # Score every recorded robot so malformed sibling rows cannot hide outside
    # the first-unit report. None of these scores establishes bench authenticity.
    expected = summarize(rows, "robot-01")
    siblings = {row["robot_id"] for row in rows} - {"robot-01"}
    for score in [expected, *(summarize(rows, robot_id) for robot_id in sorted(siblings))]:
        if score.get("placeholder_identities"):
            raise ValueError("Canonical physical trial contains placeholder identities")
    expected["physical_trial_count"] = sum(row["robot_id"] == "robot-01" for row in rows)
    required = {"robot_id", "categories", "physical_acceptance_pass", "physical_trial_count"}
    present_archive = summary.keys() & _ARCHIVE_METADATA.keys()
    if present_archive not in (set(), _ARCHIVE_METADATA.keys()):
        raise ValueError("Canonical physical summary archive metadata mismatch")
    allowed = expected.keys() | _ARCHIVE_METADATA.keys()
    if not required <= summary.keys() or not summary.keys() <= allowed:
        raise ValueError("Canonical physical summary schema mismatch")
    for key, value in summary.items():
        expected_value = _ARCHIVE_METADATA[key] if key in _ARCHIVE_METADATA else expected[key]
        # JSON comparison distinguishes booleans, integers and floating-point values.
        if json.dumps(value, sort_keys=True) != json.dumps(expected_value, sort_keys=True):
            raise ValueError(f"Canonical physical summary disagrees with CSV: {key}")
