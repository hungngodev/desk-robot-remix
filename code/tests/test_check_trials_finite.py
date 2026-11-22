"""Physical A5 evidence must not pass with impossible numeric measurements."""

import csv
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_trials.py"
spec = importlib.util.spec_from_file_location("check_trials", SCRIPT)
assert spec is not None and spec.loader is not None
check_trials = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_trials)


def trial_rows():
    rows = []
    for category in ("key", "candy"):
        for number in range(1, 11):
            rows.append(
                {
                    "robot_id": "robot-01",
                    "category": category,
                    "trial": str(number),
                    "object_description": "ordinary key" if category == "key" else "wrapped candy",
                    "mass_g": "4.3",
                    "date": "2026-11-21",
                    "firmware": "verified-test-image",
                    "calibration": "bench-profile",
                    "flat_start": "true",
                    "lift_mm": "10.5" if number <= 8 else "5.0",
                    "hold_seconds": "3.5" if number <= 8 else "1.0",
                    "placed_under_control": "true",
                    "assisted": "false",
                    "notes": "test fixture, not a physical trial",
                }
            )
    return rows


def test_finite_eight_of_ten_per_object_passes_without_overclaiming():
    result = check_trials.summarize(trial_rows(), "robot-01")
    assert result["physical_acceptance_pass"] is True
    assert result["categories"]["key"] == {
        "attempts": 10,
        "successes": 8,
        "passed": True,
    }
    assert result["categories"]["candy"]["successes"] == 8
    assert check_trials.summarize([], "robot-01")["physical_acceptance_pass"] is False
    assert check_trials.summarize(trial_rows(), "robot-02")["physical_acceptance_pass"] is False


@pytest.mark.parametrize("field", ["mass_g", "lift_mm", "hold_seconds"])
@pytest.mark.parametrize("invalid", ["inf", "Infinity", "-inf", "NaN", "nan", "1e309", "", "-0.1"])
def test_nonfinite_missing_and_negative_measurements_rejected(field, invalid):
    rows = trial_rows()
    rows[0][field] = invalid
    with pytest.raises(ValueError, match=field):
        check_trials.summarize(rows, "robot-01")


@pytest.mark.parametrize("field", ["object_description", "date", "firmware", "calibration"])
def test_missing_trial_provenance_rejected(field):
    rows = trial_rows()
    rows[0][field] = "  "
    with pytest.raises(ValueError, match="Record real object"):
        check_trials.summarize(rows, "robot-01")


@pytest.mark.parametrize("invalid", ["2026-02-30", "11/21/2026", "20261121"])
def test_invalid_dates_rejected(invalid):
    rows = trial_rows()
    rows[0]["date"] = invalid
    with pytest.raises(ValueError, match="Invalid physical trial date"):
        check_trials.summarize(rows, "robot-01")


@pytest.mark.parametrize("category", ["key", "candy"])
def test_future_dated_a5_trial_cannot_count(category):
    from datetime import date, timedelta

    rows = trial_rows()
    next(r for r in rows if r["category"] == category)["date"] = (
        date.today() + timedelta(days=1)
    ).isoformat()
    with pytest.raises(ValueError, match="Future physical trial date"):
        check_trials.summarize(rows, "robot-01")


def test_current_and_past_trial_dates_remain_valid():
    from datetime import date, timedelta

    rows = trial_rows()
    rows[0]["date"] = date.today().isoformat()
    rows[10]["date"] = (date.today() - timedelta(days=365)).isoformat()
    assert check_trials.summarize(rows, "robot-01")["physical_acceptance_pass"]


def test_cli_cannot_release_future_dated_physical_trials(tmp_path):
    from datetime import date, timedelta

    rows = trial_rows()
    rows[0]["date"] = (date.today() + timedelta(days=1)).isoformat()
    path = tmp_path / "future-trials.csv"
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--file", str(path), "--require-pass"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "Future physical trial date" in result.stderr
    assert '"physical_acceptance_pass": true' not in result.stdout


def test_real_finite_failed_trial_does_not_count_as_a_success():
    rows = trial_rows()
    rows[0]["lift_mm"] = "0"
    result = check_trials.summarize(rows, "robot-01")
    assert result["categories"]["key"]["successes"] == 7
    assert result["physical_acceptance_pass"] is False


def test_require_pass_cli_rejects_unmeasured_infinity(tmp_path):
    rows = trial_rows()
    csv_path = tmp_path / "trials.csv"
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    cmd = [sys.executable, str(SCRIPT), "--file", str(csv_path), "--require-pass"]
    accepted = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert accepted.returncode == 0
    assert '"physical_acceptance_pass": true' in accepted.stdout
    rows[0]["lift_mm"] = "1e309"
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    rejected = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert rejected.returncode != 0
    assert '"physical_acceptance_pass": true' not in rejected.stdout
    assert "Invalid physical measurement: lift_mm" in rejected.stderr


@pytest.mark.parametrize(
    ("category", "field"),
    [
        ("key", "firmware"),
        ("key", "calibration"),
        ("candy", "firmware"),
        ("candy", "calibration"),
    ],
)
def test_a5_rejects_mixed_firmware_and_calibration(category, field):
    rows = trial_rows()
    next(row for row in rows if row["category"] == category)[field] = "other-setup"
    with pytest.raises(ValueError, match="same firmware and calibration"):
        check_trials.summarize(rows, "robot-01")


def test_a5_accepts_consistent_nondefault_setup_across_both_objects():
    rows = trial_rows()
    for row in rows:
        row["firmware"] = "qualified-firmware-commit"
        row["calibration"] = "calibration-record-v2"
    assert check_trials.summarize(rows, "robot-01")["physical_acceptance_pass"]


def test_a5_cli_require_pass_rejects_mixed_configuration(tmp_path):
    rows = trial_rows()
    rows[10]["calibration"] = "another-jaw-calibration"
    csv_path = tmp_path / "mixed-a5-setup.csv"
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--file", str(csv_path), "--require-pass"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "A5 trials must use the same firmware and calibration" in result.stderr
    assert '"physical_acceptance_pass": true' not in result.stdout


@pytest.mark.parametrize("duplicate", ["assisted", "firmware"])
def test_a5_cli_rejects_duplicate_column_headers(tmp_path, duplicate):
    rows = trial_rows()
    headers = list(rows[0])
    duplicate_at = headers.index(duplicate)
    headers.insert(duplicate_at, duplicate)
    csv_path = tmp_path / "contradictory-a5-headers.csv"
    with csv_path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        for row in rows:
            values = [row[header] for header in headers]
            # The later column looks admissible to DictReader while the
            # earlier column contradicts it, so last-key-wins is unsafe.
            values[duplicate_at] = "true" if duplicate == "assisted" else "old-firmware"
            writer.writerow(values)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--file", str(csv_path), "--require-pass"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "unique, nonempty column names" in result.stderr
    assert '"physical_acceptance_pass": true' not in result.stdout
