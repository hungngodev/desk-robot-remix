"""Physical A5 evidence must not pass with impossible numeric measurements."""

import csv
import importlib.util
import json
import os
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
                    "assembly_id": "robot-01-built-revA",
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



@pytest.mark.parametrize("invalid", [
    "", " ", "../robot-01", "robot 01", "robot-01\\n",
    "a" * 81, None, True,
])
def test_a5_rejects_missing_or_unidentifiable_physical_assembly(invalid):
    rows = trial_rows()
    rows[0]["assembly_id"] = invalid
    with pytest.raises(ValueError, match="physical assembly_id"):
        check_trials.summarize(rows, "robot-01")


def test_a5_rejects_spliced_key_and_candy_assemblies():
    rows = trial_rows()
    # Every existing outcome meets 8/10; same firmware/calibration alone
    # previously let two physically rebuilt machines combine into one pass.
    for row in rows:
        if row["category"] == "candy":
            row["assembly_id"] = "robot-01-rebuilt-revB"
    with pytest.raises(ValueError, match="same firmware and calibration and physical assembly"):
        check_trials.summarize(rows, "robot-01")


def test_a5_other_robot_can_use_a_separate_fitted_assembly():
    rows = trial_rows()
    rows.append({
        **rows[0], "robot_id": "robot-02",
        "assembly_id": "robot-02-built-revC",
        "category": "key", "trial": "11",
    })
    report = check_trials.summarize(rows, "robot-01")
    assert report["physical_acceptance_pass"]
    assert report["assembly_id"] == "robot-01-built-revA"


def test_a5_cli_rejects_missing_assembly_column_and_mixed_rebuilds(tmp_path):
    for mode in ("missing_column", "mixed_rebuild"):
        rows = trial_rows()
        if mode == "missing_column":
            for row in rows:
                row.pop("assembly_id")
        else:
            rows[10]["assembly_id"] = "robot-01-rebuilt-revB"
        path = tmp_path / f"{mode}.csv"
        with path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--file", str(path),
             "--robot", "robot-01", "--require-pass"],
            capture_output=True, text=True, check=False,
        )
        assert result.returncode != 0
        assert '"physical_acceptance_pass": true' not in result.stdout
        assert "physical assembly" in result.stderr

@pytest.mark.parametrize("invalid_id", [
    "", " ", "\t", "robot 01", "../robot-01", "robot-01\n",
    "a" * 41, None, True,
])
def test_a5_rejects_invalid_selected_and_recorded_robot_ids(invalid_id):
    rows = trial_rows()
    for row in rows:
        row["robot_id"] = invalid_id
    with pytest.raises(ValueError, match="Invalid A5 trial robot identity"):
        check_trials.summarize(rows, invalid_id)

    rows = trial_rows()
    rows[0]["robot_id"] = invalid_id
    with pytest.raises(ValueError, match="Invalid A5 trial robot identity"):
        check_trials.summarize(rows, "robot-01")



@pytest.mark.parametrize("invalid", [
    "0_1", "01", " 1", "1 ", "1_0", "1.0", "+1", "１",
    "", "0", "11", True, 1.9, 1, None,
])
def test_a5_trial_label_must_be_canonical_integer_string(invalid):
    rows = trial_rows()
    rows[0]["trial"] = invalid
    with pytest.raises(ValueError, match="canonical trial numbers"):
        check_trials.summarize(rows, "robot-01")


def test_a5_cli_rejects_ambiguous_trial_number_that_int_would_accept(tmp_path):
    rows = trial_rows()
    rows[0]["trial"] = "0_1"  # int("0_1") == 1; previously certified as A5 success.
    path = tmp_path / "ambiguous-trial.csv"
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--file", str(path),
         "--robot", "robot-01", "--require-pass"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "canonical trial numbers" in result.stderr
    assert '"physical_acceptance_pass": true' not in result.stdout


def test_a5_cli_cannot_certify_unidentified_20_trial_population(tmp_path):
    rows = trial_rows()
    for row in rows:
        row["robot_id"] = " "
    path = tmp_path / "unidentified-a5.csv"
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--file", str(path),
         "--robot", " ", "--require-pass"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "Invalid A5 trial robot identity" in result.stderr
    assert '"physical_acceptance_pass": true' not in result.stdout


def test_finite_eight_of_ten_per_object_passes_without_overclaiming():
    result = check_trials.summarize(trial_rows(), "robot-01")
    assert result["physical_acceptance_pass"] is True
    assert result["assembly_id"] == "robot-01-built-revA"
    assert result["assembly_identity_physically_verified"] is False
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


@pytest.mark.parametrize("malformation", ["extra", "missing"])
def test_a5_cli_rejects_row_width_mismatch(tmp_path, malformation):
    rows = trial_rows()
    csv_path = tmp_path / "malformed-a5-row.csv"
    with csv_path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        headers = list(rows[0])
        writer.writerow(headers)
        for index, row in enumerate(rows):
            values = [row[header] for header in headers]
            if index == 0 and malformation == "extra":
                values.append("true")  # Contradictory omitted assisted evidence
            elif index == 0 and malformation == "missing":
                values.pop()  # Do not infer missing notes or future metadata
            writer.writerow(values)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--file", str(csv_path), "--require-pass"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "A5 physical trial CSV row length differs from header" in result.stderr
    assert '"physical_acceptance_pass": true' not in result.stdout


@pytest.mark.parametrize("unknown_category", ["key ", "candy_wrapper", ""])
def test_unknown_selected_robot_a5_attempt_cannot_disappear(unknown_category):
    rows = trial_rows()
    rows.append({**rows[0], "category": unknown_category, "trial": "11",
                 "assisted": "true", "lift_mm": "0"})
    with pytest.raises(ValueError, match="Unrecognized physical trial category"):
        check_trials.summarize(rows, "robot-01")


def test_a5_other_robot_attempt_remains_independently_scoped():
    rows = trial_rows()
    rows.append({**rows[0], "robot_id": "robot-02", "category": "key ",
                 "trial": "11", "assisted": "true"})
    assert check_trials.summarize(rows, "robot-01")["physical_acceptance_pass"]

@pytest.mark.parametrize(("category", "field", "invalid"), [
    ("key", "assisted", ""),
    ("candy", "assisted", "unknown"),
    ("key", "placed_under_control", "n/a"),
    ("candy", "placed_under_control", ""),
    ("key", "flat_start", ""),
    ("key", "flat_start", "unmeasured"),
])
def test_a5_incomplete_outcome_cannot_fill_failed_trial_slots(category, field, invalid):
    rows = trial_rows()
    for row in rows:
        if row["category"] == category and row["trial"] in ("9", "10"):
            row[field] = invalid
    with pytest.raises(ValueError, match=field):
        check_trials.summarize(rows, "robot-01")


@pytest.mark.parametrize(("category", "field"), [
    ("key", "assisted"),
    ("candy", "placed_under_control"),
    ("key", "flat_start"),
])
def test_a5_cli_refuses_incomplete_failed_attempt_fields(tmp_path, category, field):
    rows = trial_rows()
    for row in rows:
        if row["category"] == category and row["trial"] in ("9", "10"):
            row[field] = ""
    path = tmp_path / "incomplete-a5-evidence.csv"
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--file", str(path), "--require-pass"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert field in result.stderr
    assert '"physical_acceptance_pass": true' not in result.stdout


def test_a5_candy_start_orientation_is_not_a_key_only_requirement():
    rows = trial_rows()
    for row in rows:
        if row["category"] == "candy":
            row["flat_start"] = ""
    assert check_trials.summarize(rows, "robot-01")["physical_acceptance_pass"]


def test_a5_cli_reads_utf8_under_ascii_locale(tmp_path):
    rows = trial_rows()
    rows[0]["object_description"] = "chìa khóa"
    path = tmp_path / "unicode-a5.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    result = subprocess.run(
        [sys.executable, "-X", "utf8=0", str(SCRIPT), "--file", str(path), "--require-pass"],
        env={**os.environ, "LC_ALL": "C"},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["categories"]["key"]["successes"] == 8
    assert report["physical_acceptance_pass"] is True
    assert report["assembly_identity_physically_verified"] is False


def test_a5_summary_exposes_distinct_firmware_and_calibration_and_holds_placeholders():
    rows_a = trial_rows()
    rows_b = trial_rows()
    for row in rows_a:
        row["firmware"] = "wroom-2026-11-25-sha-aaa1111"
        row["calibration"] = "jaw-cal-rev1"
    for row in rows_b:
        row["firmware"] = "wroom-2026-11-25-sha-bbb2222"
        row["calibration"] = "jaw-cal-rev2"

    report_a = check_trials.summarize(rows_a, "robot-01")
    report_b = check_trials.summarize(rows_b, "robot-01")
    assert report_a["firmware"] == "wroom-2026-11-25-sha-aaa1111"
    assert report_a["calibration"] == "jaw-cal-rev1"
    assert report_b["firmware"] == "wroom-2026-11-25-sha-bbb2222"
    assert report_b["calibration"] == "jaw-cal-rev2"
    assert report_a != report_b
    # Outcome-only CSV score remains on HOLD without a matching run manifest,
    # and placeholder identities are flagged explicitly.
    assert report_a["outcome_score_only"] is True
    assert report_a["evidence_status"] == "HOLD"
    assert report_a["assembly_identity_physically_verified"] is False

    placeholder_report = check_trials.summarize(trial_rows(), "robot-01")
    assert placeholder_report["physical_acceptance_pass"] is True
    assert placeholder_report["evidence_status"] == "HOLD"
    assert "firmware" in placeholder_report["placeholder_identities"]
    assert "calibration" in placeholder_report["placeholder_identities"]


def test_a5_cli_validates_run_manifest_and_rejects_stale_or_placeholder_provenance(tmp_path):
    import hashlib

    rows = trial_rows()
    for row in rows:
        row["firmware"] = "wroom-build-rev3"
        row["calibration"] = "jaw-profile-rev3"
        row["assembly_id"] = "pet1-revC"
        row["object_description"] = "brass house key" if row["category"] == "key" else "mint candy"
        row["notes"] = "Recorded lift and placement"
    csv_path = tmp_path / "real-shape.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    digest = hashlib.sha256(csv_path.read_bytes()).hexdigest()

    good_manifest = {
        "run_id": "run-a5-003",
        "commit_sha": "a" * 40,
        "robot_id": "robot-01",
        "assembly_id": "pet1-revC",
        "firmware": "wroom-build-rev3",
        "calibration": "jaw-profile-rev3",
        "calibration_sha": "b" * 40,
        "objective_evidence_path": "docs/records/runs/a5-003.json",
        "reviewer": "operator_hana",
        "acceptance_state": "bench_passed",
        "trials_csv_sha256": digest,
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(good_manifest), encoding="utf-8")
    ok = subprocess.run(
        [sys.executable, str(SCRIPT), "--file", str(csv_path),
         "--run-manifest", str(manifest_path), "--require-pass", "--require-manifest"],
        capture_output=True, text=True, check=False,
    )
    assert ok.returncode == 0, ok.stderr
    parsed = json.loads(ok.stdout)
    assert parsed["run_manifest_verified"] is True
    assert parsed["outcome_score_only"] is False
    assert parsed["evidence_status"] == "MANIFEST_VERIFIED_PENDING_SIGNOFF"
    assert parsed["assembly_identity_physically_verified"] is False

    for bad_patch in (
        {"calibration": "stale-cal-rev1"},
        {"commit_sha": "short-sha"},
        {"reviewer": "unknown"},
        {"trials_csv_sha256": "0" * 64},
    ):
        bad_path = tmp_path / "bad_manifest.json"
        bad_path.write_text(json.dumps({**good_manifest, **bad_patch}), encoding="utf-8")
        bad = subprocess.run(
            [sys.executable, str(SCRIPT), "--file", str(csv_path),
             "--run-manifest", str(bad_path), "--require-manifest"],
            capture_output=True, text=True, check=False,
        )
        assert bad.returncode != 0


@pytest.mark.parametrize(
    ("field", "extreme_value"),
    [
        ("mass_g", "5000.0"),
        ("lift_mm", "9999.0"),
        ("hold_seconds", "86400.0"),
    ],
)
def test_a5_rejects_finite_measurements_outside_mechanism_envelope(field, extreme_value):
    rows = trial_rows()
    rows[0][field] = extreme_value
    with pytest.raises(ValueError, match=f"Out-of-envelope physical measurement: {field}"):
        check_trials.summarize(rows, "robot-01")
