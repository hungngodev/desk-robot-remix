"""Keep all 96 playbook procedures visible without inventing evidence.

The canonical PR owns execution. A source, URL or proposed command never
becomes a physical or same-commit test receipt by changing a status string.
"""
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "docs/reviews/100_page_procedure_trace.json"
STATES = {"OPEN", "TESTED", "MEASURED", "QUALIFIED"}
EVIDENCE_CLASSES = {"source", "mixed", "physical"}


def _physical_record_url_is_traceable(url, sha):
    """Only accept an exact-commit record path in the canonical repository.

    Syntax validation is NOT external attestation that a bench run occurred.
    Human review must confirm the target object and actual raw data.
    """
    if not isinstance(url, str):
        return False
    parsed = urlsplit(url)
    prefix = f"/hungngodev/desk-robot-remix/blob/{sha}/docs/records/"
    return (parsed.scheme == "https" and parsed.netloc == "github.com"
            and not parsed.query and not parsed.fragment
            and parsed.path.startswith(prefix)
            and len(parsed.path) > len(prefix)
            and ".." not in parsed.path.split("/"))


def _valid_release_evidence(record):
    if record.get("evidence_class") not in EVIDENCE_CLASSES:
        return False
    if record["gate"] == "TESTED" and record["evidence_class"] == "physical":
        return False
    if record["gate"] == "OPEN":
        return True
    sha = record["last_verified_sha"]
    test = record["executed_test_receipt"]
    if not isinstance(sha, str) or len(sha) != 40:
        return False
    if any(ch not in "0123456789abcdef" for ch in sha):
        return False
    if not isinstance(test, dict):
        return False
    if (test.get("sha") != sha
            or type(test.get("exit_code")) is not int
            or test["exit_code"] != 0
            or not isinstance(test.get("command"), str)
            or not test["command"].strip()
            or not isinstance(test.get("url"), str)
            or not test["url"].startswith(
                "https://github.com/hungngodev/desk-robot-remix/")):
        return False
    if record["gate"] in {"MEASURED", "QUALIFIED"}:
        measured = record["physical_measurement_receipt"]
        if (not isinstance(measured, dict)
                or measured.get("result") != "pass"
                or not isinstance(measured.get("operator"), str)
                or not measured["operator"].strip()
                or measured["operator"].strip().casefold() in {
                    "bench engineer", "operator", "tester", "unknown", "tbd",
                }
                or not isinstance(measured.get("device_revision"), str)
                or not measured["device_revision"].strip()
                or measured["device_revision"].strip().casefold() in {
                    "received carrier revision", "unknown", "tbd", "generic",
                }
                or not _physical_record_url_is_traceable(
                    measured.get("raw_data_url"), sha)):
            return False
    return True


def test_all_96_playbook_procedures_have_distinct_source_and_verification_owners():
    ledger = json.loads(LEDGER.read_text())
    assert ledger["schema_version"] == 2
    assert ledger["canonical_repository"] == "hungngodev/desk-robot-remix"
    assert ledger["canonical_pr"] == 17
    assert ledger["procedure_count"] == 96
    rows = ledger["procedures"]
    assert len(rows) == 96
    assert [r["id"] for r in rows] == list(range(1, 97))
    assert [r["page"] for r in rows] == list(range(5, 101))
    assert len({r["title"] for r in rows}) == 96
    assert {r["phase"].split(" ", 1)[0] for r in rows} == {
        f"{n:02d}" for n in range(1, 13)
    }
    for row in rows:
        assert row["title"].strip()
        assert row["phase"].strip()
        assert row["source_owner"].strip()
        assert row["verification_command"].startswith("cd code && ")
        assert row["gate"] in STATES
        assert row["evidence_class"] in EVIDENCE_CLASSES
        assert _valid_release_evidence(row), row["id"]


@pytest.mark.parametrize("claimed_status", ["TESTED", "MEASURED", "QUALIFIED"])
def test_status_string_cannot_fake_same_sha_or_physical_acceptance(claimed_status):
    row = json.loads(LEDGER.read_text())["procedures"][0].copy()
    row["gate"] = claimed_status
    assert not _valid_release_evidence(row)
    row["last_verified_sha"] = "a" * 40
    row["executed_test_receipt"] = {
        "sha": "a" * 40,
        "exit_code": 0,
        "command": "cd code && python -m pytest -q tests",
        "url": "https://github.com/hungngodev/desk-robot-remix/actions/runs/1",
    }
    if claimed_status == "TESTED":
        assert _valid_release_evidence(row)
    else:
        assert not _valid_release_evidence(row)
        row["physical_measurement_receipt"] = {
            "result": "pass", "operator": "fixture_operator_001",
            "device_revision": "fixture_pcb_rev_A",
            "raw_data_url": ("https://github.com/hungngodev/desk-robot-remix/"
                             "blob/" + "a" * 40 + "/docs/records/bench.csv"),
        }
        assert _valid_release_evidence(row)


def test_procurement_and_physical_procedures_remain_open_without_bench_receipts():
    rows = json.loads(LEDGER.read_text())["procedures"]
    for row in rows:
        if row["physical_measurement_receipt"] is None:
            assert row["gate"] not in {"MEASURED", "QUALIFIED"}


def test_physical_procedures_cannot_be_promoted_by_source_only_receipts():
    rows = json.loads(LEDGER.read_text())["procedures"]
    required = {19, 24, 27, 28, 44, 65, 67, 70, 72, 77, 78, 80,
                87, 88, 89, 90, 91, 92, 94}
    assert all(rows[index - 1]["evidence_class"] == "physical"
               for index in required)
    for index in required:
        row = rows[index - 1].copy()
        row["gate"] = "TESTED"
        row["last_verified_sha"] = "a" * 40
        row["executed_test_receipt"] = {
            "sha": "a" * 40, "exit_code": 0,
            "command": "cd code && python scripts/verify_system.py --suite all",
            "url": "https://github.com/hungngodev/desk-robot-remix/actions/runs/1",
        }
        assert not _valid_release_evidence(row), index


def test_physical_receipts_reject_placeholder_or_wrong_sha_urls():
    row = json.loads(LEDGER.read_text())["procedures"][88].copy()
    assert row["evidence_class"] == "physical"
    sha = "a" * 40
    row.update(gate="MEASURED", last_verified_sha=sha)
    row["executed_test_receipt"] = {
        "sha": sha, "exit_code": 0, "command": "cd code && true",
        "url": "https://github.com/hungngodev/desk-robot-remix/actions/runs/1",
    }
    row["physical_measurement_receipt"] = {
        "result": "pass", "operator": "fixture_operator_001",
        "device_revision": "fixture_pcb_rev_A",
        "raw_data_url": "https://github.com/example/bench-trial",
    }
    assert not _valid_release_evidence(row)
    row["physical_measurement_receipt"]["raw_data_url"] = (
        "https://example.com/docs/records/bench.csv")
    assert not _valid_release_evidence(row)
    row["physical_measurement_receipt"]["raw_data_url"] = (
        "https://github.com/hungngodev/desk-robot-remix/blob/"
        + "b" * 40 + "/docs/records/bench.csv")
    assert not _valid_release_evidence(row)


def test_physical_receipts_reject_obvious_placeholder_people_and_devices():
    row = json.loads(LEDGER.read_text())["procedures"][88].copy()
    sha = "a" * 40
    row.update(gate="MEASURED", last_verified_sha=sha)
    row["executed_test_receipt"] = {
        "sha": sha, "exit_code": 0, "command": "cd code && true",
        "url": "https://github.com/hungngodev/desk-robot-remix/actions/runs/1",
    }
    row["physical_measurement_receipt"] = {
        "result": "pass", "operator": "bench engineer",
        "device_revision": "received carrier revision",
        "raw_data_url": ("https://github.com/hungngodev/desk-robot-remix/"
                         "blob/" + sha + "/docs/records/bench.csv"),
    }
    assert not _valid_release_evidence(row)
    row["physical_measurement_receipt"]["operator"] = "fixture_operator_001"
    assert not _valid_release_evidence(row)

