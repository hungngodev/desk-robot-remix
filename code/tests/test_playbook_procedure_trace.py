"""Keep all 96 playbook procedures visible without inventing evidence.

The canonical PR owns execution. A source, URL or proposed command never
becomes a physical or same-commit test receipt by changing a status string.
"""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "docs/reviews/100_page_procedure_trace.json"
STATES = {"OPEN", "TESTED", "MEASURED", "QUALIFIED"}


def _valid_release_evidence(record):
    if record["gate"] == "OPEN":
        return True
    sha = record["last_verified_sha"]
    test = record["executed_test_receipt"]
    if not isinstance(sha, str) or len(sha) != 40:
        return False
    if any(ch not in "0123456789abcdef" for ch in sha):
        return False
    if not isinstance(test, str) or not test.startswith("https://"):
        return False
    if record["gate"] in {"MEASURED", "QUALIFIED"}:
        measured = record["physical_measurement_receipt"]
        if not isinstance(measured, str) or not measured.startswith("https://"):
            return False
    return True


def test_all_96_playbook_procedures_have_distinct_source_and_verification_owners():
    ledger = json.loads(LEDGER.read_text())
    assert ledger["schema_version"] == 1
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
        assert _valid_release_evidence(row), row["id"]


@pytest.mark.parametrize("claimed_status", ["TESTED", "MEASURED", "QUALIFIED"])
def test_status_string_cannot_fake_same_sha_or_physical_acceptance(claimed_status):
    row = json.loads(LEDGER.read_text())["procedures"][0].copy()
    row["gate"] = claimed_status
    assert not _valid_release_evidence(row)
    row["last_verified_sha"] = "a" * 40
    row["executed_test_receipt"] = "https://github.com/example/verified-test"
    if claimed_status == "TESTED":
        assert _valid_release_evidence(row)
    else:
        assert not _valid_release_evidence(row)
        row["physical_measurement_receipt"] = "https://github.com/example/bench-trial"
        assert _valid_release_evidence(row)


def test_procurement_and_physical_procedures_remain_open_without_bench_receipts():
    rows = json.loads(LEDGER.read_text())["procedures"]
    for row in rows:
        if row["physical_measurement_receipt"] is None:
            assert row["gate"] not in {"MEASURED", "QUALIFIED"}
    assert all(row["gate"] == "OPEN" for row in rows)
