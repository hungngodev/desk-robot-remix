"""Real Git objects prove source and later physical evidence can have distinct SHAs.

No GitHub network, hardware or fictional checkout approval is required.
"""
import base64
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code/scripts"))
import verify_playbook_receipts as playbook
import verify_procurement_receipts as procurement

DATE = "2026-11-20"
GATE = procurement.PART_GATES[0]
REPO = "hungngodev/desk-robot-remix"


def git(folder, *args):
    return subprocess.check_output(
        ["git", *args], cwd=folder, text=True, stderr=subprocess.PIPE,
    ).strip()


def real_history(tmp_path, *, code_change=False):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.name", "Local evidence regression")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    code = tmp_path / "code"
    code.mkdir()
    (code / "controller.py").write_text("VALUE = 1\n", encoding="utf-8")
    git(tmp_path, "add", "code/controller.py")
    git(tmp_path, "commit", "-qm", "tested source")
    source_sha = git(tmp_path, "rev-parse", "HEAD")
    if code_change:
        (code / "controller.py").write_text("VALUE = 2\n", encoding="utf-8")
        git(tmp_path, "add", "code/controller.py")
        git(tmp_path, "commit", "-qm", "changed test relevant source")
    directory = tmp_path / "docs/records"
    directory.mkdir(parents=True)
    record = {
        "record_id": "part:imu:" + GATE, "source_sha": source_sha,
        "scope": "part:imu", "gate": GATE, "result": "pass",
        "reviewer": "qualified_reviewer", "tested_on": DATE,
        "device_revision": "real_inspected_board_A",
        "measurement": {"observed": "measured fixture data"},
    }
    release_raw = json.dumps({"receipts": [record]}, sort_keys=True).encode()
    (directory / "release.json").write_bytes(release_raw)
    csv_raw = (
        "procedure_id,source_sha,gate,result,operator,device_revision,"
        "tested_on,measurement\n"
        f"9,{source_sha},MEASURED,pass,qualified_reviewer,"
        f"real_inspected_board_A,{DATE},10 mm lift\n"
    ).encode()
    (directory / "procedure.csv").write_bytes(csv_raw)
    git(tmp_path, "add", "docs/records")
    git(tmp_path, "commit", "-qm", "later immutable physical evidence")
    evidence_sha = git(tmp_path, "rev-parse", "HEAD")

    def lookup(url):
        prefix = f"https://api.github.com/repos/{REPO}/"
        assert url.startswith(prefix), "Untrusted GitHub target"
        tail = url[len(prefix):]
        if tail.startswith("compare/"):
            left, right = tail[len("compare/"):].split("...", 1)
            commits = list(reversed(git(tmp_path, "rev-list",
                                        f"{left}..{right}").splitlines()))
            changed = []
            for line in git(tmp_path, "diff", "--name-status", left, right).splitlines():
                status, filename = line.split("\t", 1)
                changed.append({"filename": filename,
                                "status": {"A": "added", "M": "modified",
                                           "D": "removed"}[status]})
            return {
                "status": "ahead" if git(tmp_path, "merge-base", left, right) == left
                          else "diverged",
                "ahead_by": len(commits),
                "total_commits": len(commits),
                "merge_base_commit": {"sha": git(tmp_path, "merge-base", left, right)},
                "commits": [{"sha": sha} for sha in commits],
                "files": changed,
            }
        if tail.startswith("contents/docs/records/"):
            path, revision = tail[len("contents/"):].split("?ref=", 1)
            raw = subprocess.check_output(
                ["git", "show", f"{revision}:{path}"], cwd=tmp_path,
            )
            # This is the raw Git blob, not a mocked source-file string.
            return {"type": "file", "size": len(raw), "encoding": "base64",
                    "content": base64.b64encode(raw).decode()}
        raise AssertionError("Unexpected repository API path " + tail)

    receipt = {
        **record,
        "artifact_sha256": hashlib.sha256(release_raw).hexdigest(),
        "evidence_url": f"https://github.com/{REPO}/blob/{evidence_sha}"
                        "/docs/records/release.json",
    }
    procedure = {
        "id": 9, "gate": "MEASURED",
        "physical_measurement_receipt": {
            "source_sha": source_sha,
            "artifact_sha256": hashlib.sha256(csv_raw).hexdigest(),
            "raw_data_url": f"https://github.com/{REPO}/blob/{evidence_sha}"
                            "/docs/records/procedure.csv",
            "operator": "qualified_reviewer",
            "device_revision": "real_inspected_board_A",
            "tested_on": DATE,
        },
    }
    return source_sha, evidence_sha, lookup, receipt, procedure


def test_later_evidence_commit_attests_exact_real_git_source_and_blob(tmp_path):
    source, later, lookup, receipt, procedure = real_history(tmp_path)
    assert source != later
    assert playbook.source_unchanged_since_test(source, later, lookup)
    assert procurement.verified_scoped_record(receipt, later, lookup)
    assert playbook.verified_procedure_record(procedure, later, lookup)
    assert git(tmp_path, "rev-parse", f"{later}:docs/records/release.json")


def test_wrong_artifact_digest_or_untrusted_revision_cannot_release(tmp_path):
    source, later, lookup, receipt, procedure = real_history(tmp_path)
    assert not procurement.verified_scoped_record(
        {**receipt, "artifact_sha256": "0" * 64}, later, lookup
    )
    assert not playbook.verified_procedure_record(
        {**procedure, "physical_measurement_receipt": {
            **procedure["physical_measurement_receipt"],
            "artifact_sha256": "0" * 64,
        }}, later, lookup,
    )
    assert not procurement.verified_scoped_record(
        {**receipt, "evidence_url": receipt["evidence_url"].replace(
            "github.com/", "example.org/")}, later, lookup,
    )
    assert not procurement.verified_scoped_record(
        {**receipt, "source_sha": "b" * 40}, later, lookup,
    )


def test_real_intervening_source_edit_invalidates_physical_evidence(tmp_path):
    source, later, lookup, receipt, procedure = real_history(
        tmp_path, code_change=True,
    )
    assert source != later
    assert not playbook.source_unchanged_since_test(source, later, lookup)
    assert not procurement.verified_scoped_record(receipt, later, lookup)
    assert not playbook.verified_procedure_record(procedure, later, lookup)
