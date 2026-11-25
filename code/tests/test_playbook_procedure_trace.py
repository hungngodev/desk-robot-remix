"""Keep all 96 playbook procedures visible without inventing evidence.

The canonical PR owns execution. A source, URL or proposed command never
becomes a physical or same-commit test receipt by changing a status string.
"""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "docs/reviews/100_page_procedure_trace.json"
STATES = {"OPEN", "TESTED", "MEASURED", "QUALIFIED"}
EVIDENCE_CLASSES = {"source", "mixed", "physical"}


def _physical_record_url_is_traceable(url, sha, receipt):
    """Check immutable record syntax; the online audit verifies ancestry."""
    if not isinstance(url, str) or receipt.get("source_sha", sha) != sha:
        return False
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    match = re.fullmatch(
        r"/hungngodev/desk-robot-remix/blob/([0-9a-f]{40})/docs/records/(.+)",
        parsed.path,
    )
    if (parsed.scheme != "https" or parsed.netloc != "github.com"
            or parsed.query or parsed.fragment or match is None
            or any(part in {"", ".", ".."} for part in match[2].split("/"))):
        return False
    if match[1] == sha:
        return True
    digest = receipt.get("artifact_sha256")
    return (receipt.get("source_sha") == sha and isinstance(digest, str)
            and re.fullmatch(r"[0-9a-f]{64}", digest) is not None)


def _valid_manual_review(record, sha):
    """A manual process gate cannot be promoted by a green build alone."""
    receipt = record.get("manual_review_receipt")
    if not isinstance(receipt, dict):
        return False
    reviewer = receipt.get("reviewer")
    url = receipt.get("review_url")
    return (
        receipt.get("sha") == sha
        and isinstance(reviewer, str)
        and reviewer.strip().casefold() not in {
            "", "unknown", "tbd", "reviewer", "tester",
        }
        and isinstance(url, str)
        and url.startswith(
            "https://github.com/hungngodev/desk-robot-remix/pull/17"
            "#issuecomment-"
        )
        and url.partition("#issuecomment-")[2].isdecimal()
    )


def _valid_ci_receipt_url(url):
    if not isinstance(url, str) or any(ord(ch) <= 32 or ord(ch) == 127 for ch in url):
        return False
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.netloc == "github.com"
        and not parsed.query
        and not parsed.fragment
        and url == f"https://github.com{parsed.path}"
        and re.fullmatch(
            r"/hungngodev/desk-robot-remix/actions/runs/[1-9][0-9]{0,19}",
            parsed.path,
        ) is not None
    )


def _valid_release_evidence(record):
    if record.get("evidence_class") not in EVIDENCE_CLASSES:
        return False
    if record["gate"] == "TESTED" and record["evidence_class"] == "physical":
        return False
    if record.get("verification_method") not in (None, "manual_review"):
        return False
    if record["gate"] == "OPEN":
        return True
    sha = record["last_verified_sha"]
    test = record["executed_test_receipt"]
    if not isinstance(sha, str) or len(sha) != 40:
        return False
    if any(ch not in "0123456789abcdef" for ch in sha):
        return False
    if (record.get("verification_method") == "manual_review"
            and not _valid_manual_review(record, sha)):
        return False
    if not isinstance(test, dict):
        return False
    if (test.get("sha") != sha
            or type(test.get("exit_code")) is not int
            or test["exit_code"] != 0
            or not isinstance(test.get("command"), str)
            or test["command"] != record["verification_command"]
            or not _valid_ci_receipt_url(test.get("url"))):
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
                    measured.get("raw_data_url"), sha, measured)):
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
        command = row["verification_command"]
        assert command.startswith("cd code && ")
        # A command that merely prints usage or collects tests can never
        # qualify any of these 96 required engineering procedures.
        assert not re.search(r"--(?:help|version|collect-only)\b|&& true\b", command)
        # Every referenced pytest target must exist in this exact checkout.
        for relative in re.findall(r"tests/[A-Za-z0-9_./-]+\.py", command):
            assert (ROOT / "code" / relative).is_file(), (row["id"], relative)
        assert row.get("verification_method") in (None, "manual_review")
        if row["id"] <= 8:
            assert row["verification_method"] == "manual_review"
        assert row["gate"] in STATES
        assert row["evidence_class"] in EVIDENCE_CLASSES
        assert _valid_release_evidence(row), row["id"]


@pytest.mark.parametrize("claimed_status", ["TESTED", "MEASURED", "QUALIFIED"])
def test_status_string_cannot_fake_same_sha_or_physical_acceptance(claimed_status):
    # An executable source task can be promoted with an actual test receipt.
    # The first eight process/review tasks require separate human evidence.
    row = json.loads(LEDGER.read_text())["procedures"][8].copy()
    row["gate"] = claimed_status
    assert not _valid_release_evidence(row)
    row["last_verified_sha"] = "a" * 40
    row["executed_test_receipt"] = {
        "sha": "a" * 40,
        "exit_code": 0,
        "command": row["verification_command"],
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
            "command": row["verification_command"],
            "url": "https://github.com/hungngodev/desk-robot-remix/actions/runs/1",
        }
        # A source-only receipt is otherwise structurally valid. Isolate
        # the physical classification as the reason for rejection.
        assert not _valid_release_evidence(row), index
        assert _valid_release_evidence({**row, "evidence_class": "source"}), index


def _physical_receipt_fixture():
    """A structurally valid synthetic receipt, never actual bench evidence."""
    row = json.loads(LEDGER.read_text())["procedures"][88].copy()
    assert row["evidence_class"] == "physical"
    sha = "a" * 40
    row.update(gate="MEASURED", last_verified_sha=sha)
    row["executed_test_receipt"] = {
        "sha": sha, "exit_code": 0, "command": row["verification_command"],
        "url": "https://github.com/hungngodev/desk-robot-remix/actions/runs/1",
    }
    row["physical_measurement_receipt"] = {
        "result": "pass", "operator": "fixture_operator_001",
        "device_revision": "fixture_pcb_rev_A",
        "raw_data_url": ("https://github.com/hungngodev/desk-robot-remix/"
                         "blob/" + sha + "/docs/records/bench.csv"),
    }
    assert _valid_release_evidence(row)
    return row


@pytest.mark.parametrize("url", [
    "https://github.com/example/bench-trial",
    "https://example.com/docs/records/bench.csv",
    ("https://github.com/hungngodev/desk-robot-remix/blob/"
     + "b" * 40 + "/docs/records/bench.csv"),
])
def test_physical_receipts_reject_placeholder_or_wrong_sha_urls(url):
    row = _physical_receipt_fixture()
    row["physical_measurement_receipt"]["raw_data_url"] = url
    assert not _valid_release_evidence(row)


@pytest.mark.parametrize(("field", "value"), [
    ("operator", "bench engineer"),
    ("device_revision", "received carrier revision"),
    ("result", "fail"),
])
def test_physical_receipts_reject_invalid_signoff(field, value):
    row = _physical_receipt_fixture()
    row["physical_measurement_receipt"][field] = value
    assert not _valid_release_evidence(row)


def test_manual_process_procedures_need_review_receipts_beyond_green_ci():
    row = json.loads(LEDGER.read_text())["procedures"][0].copy()
    sha = "a" * 40
    row["gate"] = "TESTED"
    row["last_verified_sha"] = sha
    row["executed_test_receipt"] = {
        "sha": sha, "exit_code": 0, "command": row["verification_command"],
        "url": "https://github.com/hungngodev/desk-robot-remix/actions/runs/1",
    }
    assert not _valid_release_evidence(row)
    row["manual_review_receipt"] = {
        "reviewer": "unknown",
        "sha": sha,
        "review_url": "https://github.com/hungngodev/desk-robot-remix/pull/17",
    }
    assert not _valid_release_evidence(row)
    row["manual_review_receipt"] = {
        "reviewer": "fixture_operator_001",
        "sha": sha,
        "review_url": (
            "https://github.com/hungngodev/desk-robot-remix/pull/17"
            "#issuecomment-12345"
        ),
    }
    assert _valid_release_evidence(row)
    row["executed_test_receipt"]["command"] = (
        "cd code && python scripts/verify_system.py --help"
    )
    assert not _valid_release_evidence(row)


def test_all_tof_and_handling_procedures_use_existing_distinct_targets():
    rows = json.loads(LEDGER.read_text())["procedures"]
    known = {x["id"]: x["verification_command"] for x in rows}
    for index in range(25, 33):
        assert "test_tof_mux.py" not in known[index]
        assert "--help" not in known[index]
    assert "test_handling.py" in known[31]
    assert "test_pet.py" in known[32]
    assert "test_i2c_electrical_preflight.py" in known[27]
    assert len(set(known[i] for i in range(25, 33))) >= 6


def test_later_physical_record_requires_explicit_source_and_digest():
    row = _physical_receipt_fixture()
    measured = row["physical_measurement_receipt"]
    sha = row["last_verified_sha"]
    measured["raw_data_url"] = measured["raw_data_url"].replace(sha, "b" * 40)
    assert not _valid_release_evidence(row)
    measured["source_sha"] = sha
    assert not _valid_release_evidence(row)
    measured["artifact_sha256"] = "c" * 64
    assert _valid_release_evidence(row)
    measured["source_sha"] = "b" * 40
    assert not _valid_release_evidence(row)

@pytest.mark.parametrize("url", [
    "https://github.com/hungngodev/desk-robot-remix/",
    "https://github.com/hungngodev/desk-robot-remix/pull/17",
    "https://github.com/hungngodev/desk-robot-remix/actions/runs/0",
    "https://github.com/hungngodev/desk-robot-remix/actions/runs/01",
    "https://github.com/hungngodev/desk-robot-remix/actions/runs/1?attempt=2",
    "https://github.com/hungngodev/desk-robot-remix/actions/runs/1#jobs",
    "https://github.com/hungngodev/desk-robot-remix/actions/runs/1?",
    "https://github.com/hungngodev/desk-robot-remix/actions/runs/1#",
    "https://github.com/hungngodev/desk-robot-remix/actions/runs/123456789012345678901",
    "https://github.com/hungngodev/desk-robot-remix/actions/runs/1\n",
    "https://[broken",
    None,
])
def test_invalid_ci_receipt_url_cannot_promote_ledger(url):
    row = _physical_receipt_fixture()
    row["executed_test_receipt"]["url"] = url
    assert not _valid_release_evidence(row)


def test_valid_ci_receipt_url_is_structural_only():
    assert _valid_ci_receipt_url("https://github.com/hungngodev/desk-robot-remix/actions/runs/1")

