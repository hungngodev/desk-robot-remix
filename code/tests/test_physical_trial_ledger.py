"""The canonical physical ledger must not ingest simulation or stale scores."""

import csv
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/physical_trial_ledger.py"
spec = importlib.util.spec_from_file_location("physical_trial_ledger", SCRIPT)
assert spec is not None and spec.loader is not None
ledger = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ledger)


def zero_score(rows, robot_id):
    assert rows == []
    return {
        "robot_id": robot_id,
        "categories": {
            category: {"attempts": 0, "successes": 0, "passed": False}
            for category in ("key", "candy")
        },
        "physical_acceptance_pass": False,
    }


def write_ledger(tmp_path, rows=(), headers=None, patch=None):
    records = tmp_path / "docs/records"
    (records / "reports").mkdir(parents=True)
    with (records / "physical-trials.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers or ledger.COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    summary = {**zero_score([], "robot-01"), "physical_trial_count": 0, **(patch or {})}
    path = records / "reports/physical-summary.json"
    path.write_text(json.dumps(summary), encoding="utf-8")
    return path


def test_header_only_ledger_reports_zero(tmp_path):
    write_ledger(tmp_path)
    ledger.validate_canonical_ledger(tmp_path, zero_score)


@pytest.mark.parametrize("patch", [
    {"physical_trial_count": 20}, {"physical_trial_count": False},
    {"physical_trial_count": 0.0}, {"physical_acceptance_pass": True},
    {"categories": {"key": {"attempts": 10, "successes": 8, "passed": True}}},
    {"simulated": True},
])
def test_empty_csv_cannot_claim_physical_progress(tmp_path, patch):
    write_ledger(tmp_path, patch=patch)
    with pytest.raises(ValueError, match="Canonical physical summary"):
        ledger.validate_canonical_ledger(tmp_path, zero_score)


@pytest.mark.parametrize("field, value", [
    ("notes", "test fixture, not a physical trial"),
    ("firmware", "verified-test-image"),
    ("calibration", "simulation_profile"),
    ("assembly_id", "synthetic-robot"),
    ("object_description", "mock candy"),
])
def test_explicit_nonphysical_rows_are_rejected_before_scoring(tmp_path, field, value):
    row = dict.fromkeys(ledger.COLUMNS, "real")
    row[field] = value
    write_ledger(tmp_path, rows=[row])
    with pytest.raises(ValueError, match=f"Nonphysical trial provenance: {field}"):
        ledger.validate_canonical_ledger(tmp_path, zero_score)


def test_empty_csv_still_requires_exact_schema(tmp_path):
    write_ledger(tmp_path, headers=ledger.COLUMNS[:-1])
    with pytest.raises(ValueError, match="CSV schema mismatch"):
        ledger.validate_canonical_ledger(tmp_path, zero_score)


def test_duplicate_summary_count_is_rejected(tmp_path):
    path = write_ledger(tmp_path)
    path.write_text(path.read_text().replace('{', '{"physical_trial_count": 20,', 1))
    with pytest.raises(ValueError, match="Duplicate physical summary key"):
        ledger.validate_canonical_ledger(tmp_path, zero_score)


def test_check_trials_canonical_cli_uses_strict_ledger(tmp_path):
    scripts = tmp_path / "code/scripts"
    scripts.mkdir(parents=True)
    for name in ("check_trials.py", "physical_trial_ledger.py"):
        shutil.copyfile(SCRIPT.parent / name, scripts / name)
    path = write_ledger(tmp_path)
    command = [sys.executable, str(scripts / "check_trials.py")]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["physical_trial_count"] == 0
    csv_path = path.parents[1] / "physical-trials.csv"
    row = dict.fromkeys(ledger.COLUMNS, "real")
    row["notes"] = "simulated trial"
    with csv_path.open("a", newline="", encoding="utf-8") as stream:
        csv.DictWriter(stream, fieldnames=ledger.COLUMNS).writerow(row)
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert "Nonphysical trial provenance: notes" in result.stderr


def test_external_fixture_cannot_bind_physical_manifest(tmp_path):
    row = dict.fromkeys(ledger.COLUMNS, "real")
    row["notes"] = "not a physical trial"
    path = write_ledger(tmp_path, rows=[row])
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT.parent / "check_trials.py"), "--file",
         str(path.parents[1] / "physical-trials.csv"), "--run-manifest", str(manifest)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "Nonphysical trial provenance: notes" in result.stderr
