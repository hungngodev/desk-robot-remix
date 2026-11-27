"""Keep all 96 playbook procedures visible without inventing evidence.

The canonical PR owns execution. A source, URL or proposed command never
becomes a physical or same-commit test receipt by changing a status string.
"""
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "docs/reviews/100_page_procedure_trace.json"
STATES = {"OPEN", "TESTED", "MEASURED", "QUALIFIED"}
EVIDENCE_CLASSES = {"source", "mixed", "physical"}

_VERIFY_SPEC = importlib.util.spec_from_file_location(
    "playbook_receipt_policy",
    ROOT / "code/scripts/verify_playbook_receipts.py",
)
_POLICY = importlib.util.module_from_spec(_VERIFY_SPEC)
_VERIFY_SPEC.loader.exec_module(_POLICY)
MANUAL_REVIEW_PROCEDURE_IDS = _POLICY.MANUAL_REVIEW_PROCEDURE_IDS
PHYSICAL_PROCEDURE_IDS = _POLICY.PHYSICAL_PROCEDURE_IDS
MIXED_PROCEDURE_IDS = _POLICY.MIXED_PROCEDURE_IDS
REQUIRED_PROCEDURE_COMMAND_TOKENS = _POLICY.REQUIRED_PROCEDURE_COMMAND_TOKENS


_parse_ledger = _POLICY.parse_ledger


def _load_ledger():
    return _parse_ledger(LEDGER.read_text(encoding="utf-8"))


def _physical_record_url_is_traceable(url, sha, receipt):
    """Check immutable record syntax; the online audit verifies ancestry."""
    if not isinstance(url, str) or receipt.get("source_sha", sha) != sha:
        return False
    if any(ord(ch) <= 32 or ord(ch) == 127 for ch in url):
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
            or url != f"https://github.com{parsed.path}"):
        return False
    for part in match[2].split("/"):
        if re.search(r"%(?![0-9a-fA-F]{2})", part):
            return False
        try:
            decoded = unquote(part, errors="strict")
        except UnicodeError:
            return False
        if (decoded in {"", ".", ".."}
                or any(ch in decoded for ch in "/\\%")
                or any(ord(ch) < 32 or ord(ch) == 127 for ch in decoded)):
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
        and re.fullmatch(r"[1-9][0-9]{0,19}", url.partition("#issuecomment-")[2]) is not None
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
    identifier = record.get("id")
    if identifier in PHYSICAL_PROCEDURE_IDS and record.get("evidence_class") != "physical":
        return False
    if identifier in MIXED_PROCEDURE_IDS and record.get("evidence_class") == "source":
        return False
    if (identifier in MANUAL_REVIEW_PROCEDURE_IDS
            and record.get("verification_method") != "manual_review"):
        return False
    command = record.get("verification_command", "")
    if not _POLICY.valid_procedure_command(identifier, command):
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


def _missing_procedure_paths(row, root):
    """Resolve explicit owners and code-relative command paths in the checkout."""
    owners = re.findall(
        r"(?<![\w./-])(?:code|docs)/[\w./-]+"
        r"|(?<![\w./-])[\w.-]+\.(?:py|md|json|h|hpp|cpp|cc|ini|scad|sh|txt)\b",
        row["source_owner"],
    )
    targets = re.findall(
        r"(?<![\w./-])(?:tests|scripts|firmware|laptop|config)/[\w./-]+",
        row["verification_command"],
    )
    missing = []
    for relative in owners + [f"code/{target}" for target in targets]:
        path = root / relative
        if not (path.is_file() if path.suffix else path.is_dir()):
            missing.append(relative)
    return missing


@pytest.mark.parametrize(("owner", "command", "expected"), [
    ("docs/missing.md", "cd code && git rev-parse HEAD", ["docs/missing.md"]),
    ("missing.py", "cd code && git rev-parse HEAD", ["missing.py"]),
    ("AGENTS.md", "cd code && python scripts/missing.py", ["code/scripts/missing.py"]),
    ("AGENTS.md", "cd code && cmake -S firmware/missing -B /tmp/body-build",
     ["code/firmware/missing"]),
    ("AGENTS.md", "cd code && pytest tests/missing.py", ["code/tests/missing.py"]),
    ("code/firmware/body and docs/PLAN.md", "cd code && python scripts/verify_system.py", []),
    ("PR #17 metadata", "cd code && git diff origin/codex/initial-remix...HEAD", []),
    ("AGENTS.md", "cd code && cmake -S firmware/body -B /tmp/body-build", []),
    ("code/tests/fake.py", "cd code && git rev-parse HEAD", ["code/tests/fake.py"]),
])
def test_procedure_path_references_reject_stale_paths(tmp_path, owner, command, expected):
    for relative in ("AGENTS.md", "docs/PLAN.md", "code/scripts/verify_system.py"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    (tmp_path / "code/firmware/body").mkdir(parents=True)
    (tmp_path / "code/tests/fake.py").mkdir(parents=True)
    row = {"source_owner": owner, "verification_command": command}
    assert _missing_procedure_paths(row, tmp_path) == expected


def test_all_96_playbook_procedures_have_distinct_source_and_verification_owners():
    ledger = _load_ledger()
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
        # Source owners, scripts, tests and firmware paths must all resolve.
        missing = _missing_procedure_paths(row, ROOT)
        assert not missing, (row["id"], missing)
        assert row.get("verification_method") in (None, "manual_review")
        if row["id"] in MANUAL_REVIEW_PROCEDURE_IDS:
            assert row["verification_method"] == "manual_review"
        assert row["gate"] in STATES
        assert row["evidence_class"] in EVIDENCE_CLASSES
        assert _valid_release_evidence(row), row["id"]


@pytest.mark.parametrize("claimed_status", ["TESTED", "MEASURED", "QUALIFIED"])
def test_status_string_cannot_fake_same_sha_or_physical_acceptance(claimed_status):
    # An executable source task can be promoted with an actual test receipt.
    # The first eight process/review tasks require separate human evidence.
    row = _load_ledger()["procedures"][8].copy()
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
    rows = _load_ledger()["procedures"]
    for row in rows:
        if row["physical_measurement_receipt"] is None:
            assert row["gate"] not in {"MEASURED", "QUALIFIED"}


def test_physical_procedures_cannot_be_promoted_by_source_only_receipts():
    rows = _load_ledger()["procedures"]
    assert {row["id"] for row in rows if row["evidence_class"] == "physical"} == (
        PHYSICAL_PROCEDURE_IDS
    )
    for index in sorted(PHYSICAL_PROCEDURE_IDS):
        row = rows[index - 1].copy()
        row["gate"] = "TESTED"
        row["last_verified_sha"] = "a" * 40
        row["executed_test_receipt"] = {
            "sha": "a" * 40, "exit_code": 0,
            "command": row["verification_command"],
            "url": "https://github.com/hungngodev/desk-robot-remix/actions/runs/1",
        }
        # Physical procedures cannot promote as TESTED or downgrade to mixed/source.
        assert not _valid_release_evidence(row), index
        for downgraded_class in ("mixed", "source"):
            assert not _valid_release_evidence({
                **row, "evidence_class": downgraded_class,
            }), (index, downgraded_class)


def _physical_receipt_fixture():
    """A structurally valid synthetic receipt, never actual bench evidence."""
    row = _load_ledger()["procedures"][88].copy()
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
    row = _load_ledger()["procedures"][0].copy()
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
    rows = _load_ledger()["procedures"]
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


@pytest.mark.parametrize("suffix", [
    "bench.csv\n", "bench.csv?", "bench.csv#",
    "%2e%2e/bench.csv", "%252e%252e/bench.csv",
    "x%2fy.csv", "x%5cy.csv", "x%00.csv", "x%ZZ.csv", "x%FF.csv",
])
def test_physical_record_rejects_ambiguous_encoded_paths(suffix):
    row = _physical_receipt_fixture()
    receipt = row["physical_measurement_receipt"]
    receipt["raw_data_url"] = receipt["raw_data_url"].removesuffix("bench.csv") + suffix
    assert not _valid_release_evidence(row)


def test_physical_record_rejects_leading_whitespace():
    row = _physical_receipt_fixture()
    receipt = row["physical_measurement_receipt"]
    receipt["raw_data_url"] = " " + receipt["raw_data_url"]
    assert not _valid_release_evidence(row)


@pytest.mark.parametrize("suffix", ["2026/bench.csv", "bench%20trial.csv"])
def test_physical_record_accepts_unambiguous_nested_or_encoded_names(suffix):
    row = _physical_receipt_fixture()
    receipt = row["physical_measurement_receipt"]
    receipt["raw_data_url"] = receipt["raw_data_url"].removesuffix("bench.csv") + suffix
    assert _valid_release_evidence(row)


@pytest.mark.parametrize("suffix", ["0", "01", "１２３", "123456789012345678901"])
def test_manual_review_rejects_noncanonical_comment_ids(suffix):
    sha = "a" * 40
    record = {
        "manual_review_receipt": {
            "reviewer": "fixture_operator_001",
            "sha": sha,
            "review_url": (
                "https://github.com/hungngodev/desk-robot-remix/pull/17#issuecomment-"
                + suffix
            ),
        },
    }
    assert not _valid_manual_review(record, sha)


@pytest.mark.parametrize("raw", [
    '{"gate":"OPEN","gate":"QUALIFIED"}',
    '{"procedures":[{"gate":"OPEN","gate":"QUALIFIED"}]}',
    '{"executed_test_receipt":{"exit_code":1,"exit_code":0}}',
    '{"value":NaN}', '{"value":Infinity}', '{"value":-Infinity}',
    '{"value":1e999}',
])
def test_procedure_ledger_rejects_ambiguous_or_nonfinite_json(raw):
    with pytest.raises(ValueError):
        _parse_ledger(raw)


def test_procedure_ledger_accepts_unambiguous_finite_json():
    assert _parse_ledger('{"gate":"OPEN","value":1.25}') == {
        "gate": "OPEN", "value": 1.25,
    }


@pytest.mark.parametrize("extra", [
    '"schema_version": 2, ',
    '"unused": NaN, ',
    '"unused": Infinity, ',
    '"unused": -Infinity, ',
    '"unused": 1e999, ',
    '"unused": 1e-999, ',
    '"unused": 9223372036854775808, ',
    '"unused": {"nested": 1, "nested": 2}, ',
    '"unused": ',
    "",
])
def test_standalone_ledger_cli_rejects_invalid_json_before_audit(tmp_path, extra):
    ledger = _load_ledger()
    for row in ledger["procedures"]:
        row["gate"] = "OPEN"
    raw = json.dumps(ledger)
    if extra:
        raw = "{" + extra + raw[1:]
    else:
        raw = raw.replace('"gate": "OPEN"', '"gate": "OPEN", "gate": "OPEN"', 1)
    path = tmp_path / "ledger.json"
    path.write_text(raw, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(ROOT / "code/scripts/verify_playbook_receipts.py"),
         "--ledger", str(path)],
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode == 1
    assert "INCOMPLETE: invalid playbook ledger" in result.stderr
    assert "No procedures promoted" not in result.stdout
    assert "Verified GitHub metadata" not in result.stdout


def test_standalone_ledger_cli_accepts_complete_open_ledger(tmp_path):
    ledger = _load_ledger()
    for row in ledger["procedures"]:
        row["gate"] = "OPEN"
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(ledger), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(ROOT / "code/scripts/verify_playbook_receipts.py"),
         "--ledger", str(path)],
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "No procedures promoted. No live evidence receipts checked" in result.stdout


def test_rows_65_to_80_bind_exact_required_tokens_and_manual_reviews():
    rows = _load_ledger()["procedures"]
    sha = "a" * 40
    for proc_id in range(65, 81):
        row = rows[proc_id - 1].copy()
        tokens = REQUIRED_PROCEDURE_COMMAND_TOKENS[proc_id]
        assert tokens
        assert all(tok in row["verification_command"] for tok in tokens), proc_id
        if proc_id in {66, 75}:
            assert proc_id in MANUAL_REVIEW_PROCEDURE_IDS
            assert row["verification_method"] == "manual_review"
            no_review = {
                **row,
                "gate": "TESTED",
                "last_verified_sha": sha,
                "executed_test_receipt": {
                    "sha": sha, "exit_code": 0,
                    "command": row["verification_command"],
                    "url": "https://github.com/hungngodev/desk-robot-remix/actions/runs/1",
                },
            }
            assert not _valid_release_evidence(no_review), proc_id
        # Swapping to an unrelated target test must fail command binding.
        mismatched = {
            **row,
            "verification_command": "cd code && pytest -q tests/test_unrelated_placeholder_target.py",
        }
        assert not _valid_release_evidence(mismatched), proc_id


def test_rows_9_to_15_bind_requirement_specific_tests_without_placeholder_reuse():
    rows = _load_ledger()["procedures"]
    commands = {proc_id: rows[proc_id - 1]["verification_command"] for proc_id in range(9, 16)}
    assert len(set(commands.values())) == len(commands)
    for proc_id in range(9, 16):
        row = rows[proc_id - 1].copy()
        tokens = REQUIRED_PROCEDURE_COMMAND_TOKENS[proc_id]
        assert all(tok in row["verification_command"] for tok in tokens), proc_id
        bad_cmd = (
            "cd code && python -m pytest -q tests/test_unrelated_placeholder_target.py"
            if proc_id == 9
            else "cd code && python -m pytest -q tests/test_complete_component_ownership.py"
        )
        mismatched = {**row, "verification_command": bad_cmd}
        assert not _valid_release_evidence(mismatched), proc_id


def test_rows_17_to_24_bind_requirement_specific_tests_without_placeholder_reuse():
    rows = _load_ledger()["procedures"]
    for proc_id in range(17, 25):
        row = rows[proc_id - 1].copy()
        tokens = REQUIRED_PROCEDURE_COMMAND_TOKENS.get(proc_id, ())
        assert tokens, proc_id
        assert all(tok in row["verification_command"] for tok in tokens), proc_id
        mismatched = {
            **row,
            "verification_command": "cd code && python -m pytest -q tests/test_power_preflight.py tests/test_dc_motor_watchdog_contract.py"
            if proc_id != 17
            else "cd code && python -m pytest -q tests/test_unrelated_placeholder_target.py",
        }
        assert not _valid_release_evidence(mismatched), proc_id
