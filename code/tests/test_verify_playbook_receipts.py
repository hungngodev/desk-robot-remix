"""Online playbook receipts must be checked against actual GitHub metadata."""
import importlib.util
from pathlib import Path
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "playbook_online_receipts",
    ROOT / "code/scripts/verify_playbook_receipts.py",
)
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)
SHA = "a" * 40
RUN = "https://github.com/hungngodev/desk-robot-remix/actions/runs/42"
RAW = ("https://github.com/hungngodev/desk-robot-remix/blob/"
       + SHA + "/docs/records/bench.csv")


def lookup(url):
    if url.endswith("/actions/runs/42"):
        return {"head_sha": SHA, "name": "Host verification",
                "event": "pull_request",
                "head_branch": "impl/mac-hardware-safety-preflight-2026-11-10",
                "head_repository": {"full_name": "hungngodev/desk-robot-remix"},
                "status": "completed", "conclusion": "success"}
    if "/contents/docs/records/bench.csv?ref=" in url:
        return {"type": "file", "size": 52}
    raise AssertionError("Unexpected URL " + url)


def promoted(gate="TESTED"):
    return {"procedures": [{
        "id": 9, "evidence_class": "mixed",
        "gate": gate, "last_verified_sha": SHA,
        "verification_command": "cd code && python -m pytest -q tests/test_complete_component_ownership.py",
        "executed_test_receipt": {
            "sha": SHA, "exit_code": 0, "url": RUN,
            "command": "cd code && python -m pytest -q tests/test_complete_component_ownership.py",
        },
        "physical_measurement_receipt": {
            "result": "pass", "raw_data_url": RAW,
            "operator": "fixture_operator_001",
            "device_revision": "fixture_carrier_rev_A",
        },
    }]}


def test_open_playbook_requires_no_network():
    assert verify.audit({"procedures": [{"id": 89, "gate": "OPEN"}]},
                        lambda url: 1 / 0) == []


def test_verified_run_and_pinned_physical_record_paths():
    assert verify.audit(promoted("MEASURED"), lookup) == []
    assert verify.verified_actions_run(RUN, SHA, lookup)
    assert verify.verified_raw_record(RAW, SHA, lookup)


def test_ci_fails_if_github_reports_failure_or_wrong_sha():
    def failed(_):
        return {"head_sha": "b" * 40, "status": "completed",
                "conclusion": "failure"}
    assert "CI run not verified" in verify.audit(promoted(), failed)[0]


def test_physical_record_must_exist_at_same_commit():
    bad = promoted("MEASURED")
    bad["procedures"][0]["physical_measurement_receipt"]["raw_data_url"] = (
        RAW.replace(SHA, "b" * 40))
    assert any("raw physical record not found" in item
               for item in verify.audit(bad, lookup))

    def empty_record(url):
        if "/contents/" in url:
            return {"type": "file", "size": 0}
        return lookup(url)
    assert any("raw physical record not found" in item
               for item in verify.audit(promoted("MEASURED"), empty_record))


def test_unavailable_api_cannot_approve_evidence():
    def offline(_):
        raise URLError("offline")
    assert any("CI lookup failed" in item
               for item in verify.audit(promoted(), offline))


def test_wrong_run_host_is_rejected_without_network():
    fake = promoted()
    fake["procedures"][0]["executed_test_receipt"]["url"] = (
        "https://example.com/hungngodev/desk-robot-remix/actions/runs/42")
    assert "CI run not verified" in verify.audit(fake, lookup)[0]


def test_matching_sha_from_unrelated_workflow_does_not_qualify():
    def unrelated(_):
        return {"head_sha": SHA, "name": "Unrelated workflow",
                "status": "completed", "conclusion": "success"}
    assert "CI run not verified" in verify.audit(promoted(), unrelated)[0]


def test_standalone_audit_rejects_source_only_physical_assembly_claim():
    row = promoted()["procedures"][0]
    row["id"] = 89
    row["evidence_class"] = "physical"
    assert any("physical task cannot be source-only TESTED" in item
               for item in verify.audit({"procedures": [row]}, lookup))


def test_standalone_audit_rejects_unclassified_promotion():
    row = promoted()["procedures"][0]
    row.pop("evidence_class")
    assert any("missing evidence class" in item
               for item in verify.audit({"procedures": [row]}, lookup))


def test_online_audit_refuses_nonexecuting_or_mismatched_playbook_commands():
    for invalid in [
        "cd code && python scripts/verify_system.py --help",
        "cd code && python -m pytest --collect-only",
        "cd code && true",
        "cd code && python -m pytest -q tests/not-the-receipt.py",
    ]:
        bad = promoted("TESTED")
        bad["procedures"][0]["verification_command"] = invalid
        assert any(
            "executable command receipt mismatch" in msg
            for msg in verify.audit(bad, lookup)
        )


def test_online_manual_review_requires_real_matching_pr_comment():
    manually_reviewed = promoted("TESTED")
    row = manually_reviewed["procedures"][0]
    row.update(id=4, evidence_class="source", verification_method="manual_review")
    sha = row["last_verified_sha"]
    comment_url = (
        "https://github.com/hungngodev/desk-robot-remix/pull/17"
        "#issuecomment-5678"
    )
    row["manual_review_receipt"] = {
        "sha": sha, "reviewer": "physical_owner", "review_url": comment_url,
    }

    def reviewed(url):
        if url.endswith("/issues/comments/5678"):
            return {
                "html_url": comment_url,
                "body": f"ACCEPTED procedure 4 at {sha}",
                "author_association": "OWNER",
                "user": {"login": "physical_owner", "type": "User"},
            }
        return lookup(url)

    assert verify.audit(manually_reviewed, reviewed) == []
    bad = row["manual_review_receipt"]
    bad["reviewer"] = "unknown"
    assert any(
        "manual review not verified" in msg
        for msg in verify.audit(manually_reviewed, reviewed)
    )
    bad["reviewer"] = "physical_owner"
    bad["sha"] = "b" * 40
    assert any(
        "manual review not verified" in msg
        for msg in verify.audit(manually_reviewed, reviewed)
    )
    bad["sha"] = sha
    def fabricated(url):
        if url.endswith("/issues/comments/5678"):
            return {"html_url": comment_url, "body": "No matching acceptance or SHA",
                    "author_association": "OWNER",
                    "user": {"login": "physical_owner", "type": "User"}}
        return lookup(url)
    assert any(
        "manual review not verified" in msg
        for msg in verify.audit(manually_reviewed, fabricated)
    )


def test_online_physical_receipts_refuse_placeholder_signoff_identities():
    for field, wrong in [
        ("operator", "bench engineer"),
        ("operator", ""),
        ("device_revision", "received carrier revision"),
        ("device_revision", "unknown"),
    ]:
        bad = promoted("MEASURED")
        bad["procedures"][0]["physical_measurement_receipt"][field] = wrong
        assert any(
            "incomplete physical signoff" in item
            for item in verify.audit(bad, lookup)
        )


def test_manual_or_other_branch_success_cannot_qualify_pr17():
    canonical = lookup("https://api.github.com/repos/hungngodev/"
                       "desk-robot-remix/actions/runs/42")
    for overrides in (
        {"event": "workflow_dispatch"},
        {"event": "push"},
        {"head_branch": "main"},
        {"head_repository": {"full_name": "someone/other-repo"}},
        {"head_repository": None},
    ):
        def wrong_origin(_url, changes=overrides):
            return {**canonical, **changes}
        assert not verify.verified_actions_run(RUN, SHA, wrong_origin)
        assert any("CI run not verified" in problem
                   for problem in verify.audit(promoted(), wrong_origin))


def test_manual_review_mentioned_sha_is_not_authorized_acceptance():
    row = promoted("TESTED")["procedures"][0]
    row.update(id=4, evidence_class="source", verification_method="manual_review")
    url = ("https://github.com/hungngodev/desk-robot-remix/pull/17"
           "#issuecomment-101")
    row["manual_review_receipt"] = {
        "sha": SHA, "reviewer": "reviewer_a", "review_url": url,
    }
    def comment_lookup(_url, *, association="OWNER", body=None):
        if "/issues/comments/" in _url:
            return {
                "html_url": url, "author_association": association,
                "body": body if body is not None else f"ACCEPTED procedure 4 at {SHA}",
                "user": {"login": "reviewer_a", "type": "User"},
            }
        return lookup(_url)
    assert verify.verified_manual_review(row, SHA, comment_lookup)
    for association in ("NONE", "CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR"):
        assert not verify.verified_manual_review(
            row, SHA, lambda url, group=association:
            comment_lookup(url, association=group)
        )
    assert not verify.verified_manual_review(
        row, SHA, lambda url: comment_lookup(
            url, body=f"Procedure 4 proposed for review at {SHA}"
        )
    )


def test_online_audit_rejects_invalid_gate_values_without_network():
    # Even credible source and CI receipts must not promote a misspelled gate.
    for gate in ("MEASURED ", "QUALIFIED ", "TESTED ", "WEIRD", "", None, 7):
        bad = promoted(gate)
        errors = verify.audit(bad, lambda _: 1 / 0)
        assert any("unknown gate" in problem for problem in errors)


def test_online_audit_rejects_invalid_procedure_ids_without_network():
    for identifier in ("9", True, None, 0, 97):
        bad = promoted("MEASURED")
        bad["procedures"][0]["id"] = identifier
        errors = verify.audit(bad, lambda _: 1 / 0)
        assert any("invalid procedure id" in problem for problem in errors)
