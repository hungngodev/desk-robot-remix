"""Online playbook receipts must be checked against actual GitHub metadata."""
import base64
import importlib.util
import json
from pathlib import Path
from urllib.error import URLError

import pytest

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
REVIEW_URL = ("https://github.com/hungngodev/desk-robot-remix/pull/17"
              "#issuecomment-5678")


def lookup(url):
    if url.endswith("/issues/comments/5678"):
        return {"html_url": REVIEW_URL,
                "body": f"ACCEPTED procedure 9 at {SHA}",
                "author_association": "OWNER",
                "user": {"login": "physical_owner", "type": "User"}}
    if url.endswith("/actions/runs/42"):
        return {"id": 42, "run_attempt": 2,
                "path": ".github/workflows/host-verification.yml",
                "head_sha": SHA, "name": "Host verification",
                "event": "pull_request",
                "head_branch": "impl/mac-hardware-safety-preflight-2026-11-10",
                "head_repository": {"full_name": "hungngodev/desk-robot-remix"},
                "status": "completed", "conclusion": "success"}
    if url.endswith("/actions/runs/42/jobs?per_page=100"):
        jobs = [
            {"name": name, "run_id": 42, "run_attempt": 2, "head_sha": SHA,
             "status": "completed", "conclusion": "success"}
            for name in (
                "Mac conversation and memory regression",
                "Python and head host tests",
                "Body C++ host tests with sanitizers",
                "ESP32 WROOM firmware compile",
                "XIAO Sense ESP-IDF 6.1 firmware compile",
            )
        ]
        return {"jobs": jobs, "total_count": len(jobs)}
    if "/contents/docs/records/bench.csv?ref=" in url:
        raw = (
            "procedure_id,source_sha,gate,result,operator,device_revision,"
            "tested_on,measurement\n"
            f"9,{SHA},MEASURED,pass,fixture_operator_001,"
            "fixture_carrier_rev_A,2026-11-20,10 mm lift\n"
        ).encode()
        return {"type": "file", "size": len(raw), "encoding": "base64",
                "content": base64.b64encode(raw).decode()}
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
        "manual_review_receipt": {
            "sha": SHA, "reviewer": "physical_owner",
            "review_url": REVIEW_URL,
        },
        "physical_measurement_receipt": {
            "result": "pass", "raw_data_url": RAW,
            "operator": "fixture_operator_001",
            "device_revision": "fixture_carrier_rev_A",
            "tested_on": "2026-11-20",
        },
    }]}


def full_ledger_with(one_row=None):
    """Use the real 96-row OPEN ledger for successful online audit fixtures."""
    source = ROOT / "docs/reviews/100_page_procedure_trace.json"
    ledger = json.loads(source.read_text(encoding="utf-8"))
    if one_row is not None:
        identifier = one_row["id"]
        ledger["procedures"][identifier - 1] = {
            **ledger["procedures"][identifier - 1], **one_row,
        }
    return ledger


def test_open_playbook_requires_no_network():
    assert verify.audit(full_ledger_with(), lambda url: 1 / 0) == []
    partial = {"procedures": [{"id": 89, "gate": "OPEN"}]}
    assert any("incomplete procedure ledger" in err
               for err in verify.audit(partial, lambda url: 1 / 0))


def test_verified_run_and_pinned_physical_record_paths():
    assert verify.audit(full_ledger_with(promoted("MEASURED")["procedures"][0]), lookup) == []
    assert verify.verified_actions_run(RUN, SHA, lookup)
    assert verify.verified_raw_record(RAW, SHA, lookup)


@pytest.mark.parametrize("defect", [
    "missing", "skipped", "wrong_attempt", "wrong_sha", "duplicate", "wrong_run",
    "truncated",
])
def test_green_headline_cannot_promote_without_exact_required_jobs(defect):
    row = promoted("TESTED")["procedures"][0]

    def altered(url):
        response = lookup(url)
        if "jobs" not in response:
            return response
        jobs = response["jobs"]
        if defect == "missing":
            jobs.pop()
        elif defect == "skipped":
            jobs[0]["conclusion"] = "skipped"
        elif defect == "wrong_attempt":
            jobs[0]["run_attempt"] = 1
        elif defect == "wrong_sha":
            jobs[0]["head_sha"] = "b" * 40
        elif defect == "duplicate":
            jobs.append(dict(jobs[0]))
        elif defect == "wrong_run":
            jobs[0]["run_id"] = 43
        response["total_count"] = len(jobs) + (defect == "truncated")
        return response

    assert verify.verified_actions_run(RUN, SHA, altered)
    assert verify.audit(full_ledger_with(row), lookup) == []
    assert any("CI run not verified" in error
               for error in verify.audit(full_ledger_with(row), altered))


def test_required_job_lookup_failure_stays_distinct_from_failed_ci():
    def offline_jobs(url):
        if "/jobs?" in url:
            raise URLError("offline jobs endpoint")
        return lookup(url)

    row = promoted("TESTED")["procedures"][0]
    assert any("CI lookup failed" in error
               for error in verify.audit(full_ledger_with(row), offline_jobs))


def test_ci_fails_if_github_reports_failure_or_wrong_sha():
    def failed(_):
        return {"head_sha": "b" * 40, "status": "completed",
                "conclusion": "failure"}
    assert "CI run not verified" in verify.audit(promoted(), failed)[0]


def test_malformed_github_contents_envelope_is_not_a_raw_physical_receipt():
    for response in ([], None, 42, "error", {"type": "dir"}):
        assert not verify.verified_raw_record(
            RAW, SHA, lambda _, value=response: value
        )


def test_physical_record_must_exist_at_same_commit():
    bad = promoted("MEASURED")
    bad["procedures"][0]["physical_measurement_receipt"]["raw_data_url"] = (
        RAW.replace(SHA, "b" * 40))
    assert any("immutable physical record not matched" in item
               for item in verify.audit(bad, lookup))

    def empty_record(url):
        if "/contents/" in url:
            return {"type": "file", "size": 0}
        return lookup(url)
    assert any("immutable physical record not matched" in item
               for item in verify.audit(promoted("MEASURED"), empty_record))


def test_existing_unrelated_record_cannot_promote_physical_procedure():
    row = promoted("MEASURED")["procedures"][0]
    good = lookup("https://api.github.com/repos/hungngodev/"
                  "desk-robot-remix/contents/docs/records/bench.csv?ref=" + SHA)
    original = base64.b64decode(good["content"]).decode()
    for bad in (
        original.replace(f"9,{SHA}", f"11,{SHA}"),
        original.replace("10 mm lift", ""),
        original.replace("10 mm lift", "pass"),
        original.replace("2026-11-20", "2026-99-99"),
        original.replace(f"9,{SHA}", f"9,{'b' * 40}"),
        original + original.splitlines()[1] + "\n",
    ):
        raw = bad.encode()
        def altered(url, data=raw):
            if "/contents/" not in url:
                return lookup(url)
            return {**good, "size": len(data),
                    "content": base64.b64encode(data).decode()}
        assert verify.verified_raw_record(RAW, SHA, altered)
        assert not verify.verified_procedure_record(row, SHA, altered)
        assert any("immutable physical record not matched" in error
                   for error in verify.audit({"procedures": [row]}, altered))



@pytest.mark.parametrize("invalid", ["extra", "missing", "unnamed_header"])
def test_physical_csv_rejects_incomplete_or_overflowing_record(invalid):
    row = promoted("MEASURED")["procedures"][0]
    original = lookup(
        "https://api.github.com/repos/hungngodev/"
        "desk-robot-remix/contents/docs/records/bench.csv?ref=" + SHA
    )
    header, record = base64.b64decode(original["content"]).decode().splitlines()
    if invalid == "extra":
        # An omitted conflicting measurement must not disappear under None.
        corrupt = header + "\n" + record + ",unsafe_lift\n"
    elif invalid == "missing":
        corrupt = header + "\n" + record.rsplit(",", 1)[0] + "\n"
    else:
        corrupt = header + ",\n" + record + ",hidden\n"
    raw = corrupt.encode()

    def altered(url):
        if "/contents/docs/records/bench.csv" in url:
            return {**original, "size": len(raw),
                    "content": base64.b64encode(raw).decode()}
        return lookup(url)

    assert verify.verified_raw_record(RAW, SHA, altered)
    assert not verify.verified_procedure_record(row, SHA, altered)


def test_immutable_physical_record_binds_gate_signoff_and_json_measurements():
    row = promoted("MEASURED")["procedures"][0]
    assert verify.verified_procedure_record(row, SHA, lookup)
    signoff = row["physical_measurement_receipt"]
    for key, altered in (("operator", "another_person"),
                         ("device_revision", "another_board"),
                         ("tested_on", "2026-11-19")):
        old = signoff[key]
        signoff[key] = altered
        assert not verify.verified_procedure_record(row, SHA, lookup)
        signoff[key] = old
    row["gate"] = "QUALIFIED"
    assert not verify.verified_procedure_record(row, SHA, lookup)
    row["gate"] = "MEASURED"
    signoff["raw_data_url"] = RAW.replace("bench.csv", "bench.json")
    receipt = {"procedure_id": 9, "source_sha": SHA, "gate": "MEASURED",
               "result": "pass", "operator": signoff["operator"],
               "device_revision": signoff["device_revision"],
               "tested_on": signoff["tested_on"],
               "measurement": {"lift_mm": 10}}
    def json_lookup(url, records=None):
        if "/contents/" not in url:
            return lookup(url)
        data = json.dumps({"receipts": [receipt] if records is None else records}).encode()
        return {"type": "file", "size": len(data), "encoding": "base64",
                "content": base64.b64encode(data).decode()}
    assert verify.verified_procedure_record(row, SHA, json_lookup)
    assert not verify.verified_procedure_record(
        row, SHA, lambda url: json_lookup(url, [receipt, receipt]))
    assert not verify.verified_procedure_record(
        row, SHA, lambda url: json_lookup(
            url, [{**receipt, "procedure_id": 42}]))



def test_immutable_procedure_identity_rejects_boolean_float_or_padded_ids():
    row = promoted("MEASURED")["procedures"][0]
    row["id"] = 1
    signoff = row["physical_measurement_receipt"]
    signoff["raw_data_url"] = RAW.replace("bench.csv", "identities.json")
    valid = {
        "procedure_id": 1, "source_sha": SHA, "gate": "MEASURED",
        "result": "pass", "operator": signoff["operator"],
        "device_revision": signoff["device_revision"],
        "tested_on": signoff["tested_on"],
        "measurement": {"tilt_deg": 42.0},
    }

    def identity_lookup(url, value):
        if "/contents/" not in url:
            return lookup(url)
        raw = json.dumps({"receipts": [{**valid, "procedure_id": value}]}).encode()
        return {"type": "file", "size": len(raw), "encoding": "base64",
                "content": base64.b64encode(raw).decode()}

    for valid_id in (1, "1"):
        assert verify.verified_procedure_record(
            row, SHA, lambda url, v=valid_id: identity_lookup(url, v))
    for invalid in (True, 1.0, "01", "1.0", None):
        assert not verify.verified_procedure_record(
            row, SHA, lambda url, v=invalid: identity_lookup(url, v))


def test_physical_json_rejects_duplicate_pass_key_and_nonfinite_measurement():
    row = promoted("MEASURED")["procedures"][0]
    row["physical_measurement_receipt"]["raw_data_url"] = RAW.replace(
        "bench.csv", "duplicate.json",
    )
    signoff = row["physical_measurement_receipt"]
    original = {
        "procedure_id": 9, "source_sha": SHA, "gate": "MEASURED",
        "result": "pass", "operator": signoff["operator"],
        "device_revision": signoff["device_revision"],
        "tested_on": signoff["tested_on"],
        "measurement": {"lift_mm": 10},
    }
    good = json.dumps({"receipts": [original]})
    def signed_file(url, contents):
        if "/contents/" not in url:
            return lookup(url)
        data = contents.encode()
        return {"type": "file", "size": len(data), "encoding": "base64",
                "content": base64.b64encode(data).decode()}

    assert verify.verified_procedure_record(
        row, SHA, lambda url: signed_file(url, good))
    for corrupt in (
        good.replace('"result": "pass"',
                     '"result": "fail", "result": "pass"'),
        good.replace('"lift_mm": 10', '"lift_mm": NaN'),
        good.replace('"lift_mm": 10', '"lift_mm": Infinity'),
        good.replace('"lift_mm": 10', '"lift_mm": 1e9999'),
        good.replace('"lift_mm": 10', '"lift_mm": -1e9999'),
        good.replace('"lift_mm": 10', '"lift_mm": 1e-9999'),
        good.replace('"lift_mm": 10', '"lift_mm": -1e-9999'),
        good.replace('"lift_mm": 10', '"lift_mm": 1e999999999999999999999999999999'),
        good.replace('"lift_mm": 10', '"lift_mm": -1e999999999999999999999999999999'),
        good.replace('"lift_mm": 10', '"lift_mm": 1e-999999999999999999999999999999'),
        good.replace('"lift_mm": 10', '"lift_mm": -1e-999999999999999999999999999999'),
        good.replace('"lift_mm": 10', '"lift_mm": 1.0000000000000001'),
    ):
        assert not verify.verified_procedure_record(
            row, SHA, lambda url, raw=corrupt: signed_file(url, raw))


def test_immutable_physical_json_rejects_oversized_integer_tokens():
    assert verify.bounded_receipt_int("9223372036854775807") == (1 << 63) - 1
    assert verify.bounded_receipt_int("-9223372036854775808") == -(1 << 63)
    for invalid in ("9223372036854775808", "-9223372036854775809",
                    "9" * 512):
        with pytest.raises(ValueError):
            verify.bounded_receipt_int(invalid)

    row = promoted("MEASURED")["procedures"][0]
    signoff = row["physical_measurement_receipt"]
    signoff["raw_data_url"] = RAW.replace("bench.csv", "integer.json")
    record = {
        "procedure_id": 9,
        "source_sha": SHA,
        "gate": "MEASURED",
        "result": "pass",
        "operator": signoff["operator"],
        "device_revision": signoff["device_revision"],
        "tested_on": signoff["tested_on"],
        "measurement": {"lift_mm": 10},
    }
    good = json.dumps({"receipts": [record]})
    def contents(raw_text):
        data = raw_text.encode("utf-8")
        return {"type": "file", "size": len(data), "encoding": "base64",
                "content": base64.b64encode(data).decode("ascii")}

    assert verify.verified_procedure_record(
        row, SHA, lambda _: contents(good),
    )
    for invalid in ("9223372036854775808", "-9223372036854775809",
                    "9" * 512):
        changed = good.replace('"lift_mm": 10', f'"lift_mm": {invalid}')
        assert changed != good
        assert not verify.verified_procedure_record(
            row, SHA, lambda _, raw=changed: contents(raw),
        )


def test_future_date_is_not_a_completed_physical_playbook_trial():
    from datetime import date, timedelta

    row = promoted("MEASURED")["procedures"][0]
    signoff = row["physical_measurement_receipt"]
    signoff["tested_on"] = (date.today() + timedelta(days=1)).isoformat()
    signoff["raw_data_url"] = RAW.replace("bench.csv", "future.json")
    record = {
        "procedure_id": 9, "source_sha": SHA, "gate": "MEASURED",
        "result": "pass", "operator": signoff["operator"],
        "device_revision": signoff["device_revision"],
        "tested_on": signoff["tested_on"],
        "measurement": {"lift_mm": 10},
    }
    data = json.dumps({"receipts": [record]}).encode()
    def signed_file(url):
        if "/contents/" not in url:
            return lookup(url)
        return {"type": "file", "size": len(data), "encoding": "base64",
                "content": base64.b64encode(data).decode()}
    assert not verify.verified_procedure_record(row, SHA, signed_file)


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


def test_executed_receipt_requires_exact_integer_zero_exit_status():
    valid = promoted("TESTED")["procedures"][0]
    assert verify.audit(full_ledger_with(valid), lookup) == []
    for invalid in (False, True, 0.0, "0", None):
        bad = {
            **valid,
            "executed_test_receipt": {
                **valid["executed_test_receipt"], "exit_code": invalid,
            },
        }
        errors = verify.audit(full_ledger_with(bad), lookup)
        assert any("invalid source receipt" in problem for problem in errors)


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

    assert verify.audit(full_ledger_with(row), reviewed) == []
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


def test_manual_review_rejects_negated_quoted_or_ambiguous_acceptance():
    row = promoted("MEASURED")["procedures"][0]
    accepted = f"ACCEPTED procedure 9 at {SHA}"

    def reviewed(url, body):
        if url.endswith("/issues/comments/5678"):
            return {**lookup(url), "body": body}
        return lookup(url)

    for affirmative in (accepted, f"ACCEPTED procedure #9 at {SHA}"):
        def resolver(url, body=affirmative):
            return reviewed(url, body)
        assert verify.verified_manual_review(row, SHA, resolver)
        assert verify.audit(full_ledger_with(row), resolver) == []

    for rejected in (
        f"NOT {accepted}",
        f"REJECTED: previously {accepted}",
        f"> {accepted}",
        f"Discussion mentioned {accepted}",
        f"{accepted} but this trial is REJECTED",
        f"{accepted}\nNOT ACCEPTED procedure 9 at {SHA}",
        f"ACCEPTED procedure 8 at {SHA}",
        f"ACCEPTED procedure 9 at {'b' * 40}",
    ):
        def resolver(url, body=rejected):
            return reviewed(url, body)
        assert not verify.verified_manual_review(row, SHA, resolver)
        assert any(
            "manual review not verified" in problem
            for problem in verify.audit(full_ledger_with(row), resolver)
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


def test_standalone_audit_refuses_truncated_duplicate_or_foreign_ledgers():
    """The CLI must not report success when required gates disappear."""
    import copy

    complete = full_ledger_with()
    assert verify.audit(complete, lambda _: 1 / 0) == []
    variants = []
    empty = copy.deepcopy(complete)
    empty["procedures"] = []
    variants.append(empty)
    lone = copy.deepcopy(complete)
    lone["procedures"] = lone["procedures"][:1]
    variants.append(lone)
    duplicate = copy.deepcopy(complete)
    duplicate["procedures"][95] = copy.deepcopy(duplicate["procedures"][94])
    variants.append(duplicate)
    missing_physical = copy.deepcopy(complete)
    missing_physical["procedures"].pop(88)
    variants.append(missing_physical)
    out_of_order = copy.deepcopy(complete)
    out_of_order["procedures"][0], out_of_order["procedures"][1] = (
        out_of_order["procedures"][1], out_of_order["procedures"][0]
    )
    variants.append(out_of_order)
    for field, fake in (
        ("schema_version", 1), ("canonical_repository", "someone/other"),
        ("canonical_pr", 18), ("procedure_count", 1),
    ):
        mismatched = copy.deepcopy(complete)
        mismatched[field] = fake
        variants.append(mismatched)
    for invalid in variants:
        errors = verify.audit(invalid, lambda _: 1 / 0)
        assert any("incomplete procedure ledger" in error for error in errors)


def test_source_comparison_fails_closed_at_github_file_cap():
    # GitHub Compare returns at most 300 file entries even when more changed.
    # A hidden 301st path may be test-relevant code, not allowed evidence.
    evidence_sha = "b" * 40

    def comparison(paths):
        return {
            "status": "ahead",
            "ahead_by": 1,
            "total_commits": 1,
            "commits": [{"sha": evidence_sha}],
            "merge_base_commit": {"sha": SHA},
            "files": [{"status": "added", "filename": path} for path in paths],
        }

    def check(paths):
        return verify.source_unchanged_since_test(
            SHA, evidence_sha, lambda _: comparison(paths)
        )

    assert check(["docs/records/one.json"])
    assert check([f"docs/records/receipt_{i}.json" for i in range(299)])
    assert not check([f"docs/records/receipt_{i}.json" for i in range(300)])
    assert not check([f"docs/records/receipt_{i}.json" for i in range(298)]
                     + ["code/laptop/src/desk_robot/pet.py"])
    assert not check([])


def test_physical_promotion_requires_authorized_matching_pr_acceptance():
    """Matching source, measured data and a green run cannot self-approve."""
    for gate in ("MEASURED", "QUALIFIED"):
        row = promoted(gate)["procedures"][0]
        def physical_lookup(url, qualified=(gate == "QUALIFIED")):
            value = lookup(url)
            if qualified and "/contents/docs/records/bench.csv" in url:
                raw = base64.b64decode(value["content"]).replace(
                    b",MEASURED,", b",QUALIFIED,",
                )
                return {**value, "size": len(raw),
                        "content": base64.b64encode(raw).decode()}
            return value

        assert verify.audit(full_ledger_with(row), physical_lookup) == []

        missing = {**row}
        missing.pop("manual_review_receipt")
        assert any("manual review not verified" in issue
                   for issue in verify.audit(full_ledger_with(missing), lookup))

        for field, wrong in (
            ("reviewer", "unknown"),
            ("sha", "b" * 40),
            ("review_url", "https://example.org/untrusted"),
        ):
            altered = {**row, "manual_review_receipt": {
                **row["manual_review_receipt"], field: wrong,
            }}
            assert any("manual review not verified" in issue
                       for issue in verify.audit(full_ledger_with(altered), lookup))

        def unauthorized(url):
            result = lookup(url)
            if url.endswith("/issues/comments/5678"):
                return {**result, "author_association": "NONE"}
            return result

        assert any("manual review not verified" in issue
                   for issue in verify.audit(full_ledger_with(row), unauthorized))

    # The new authority gate does not force reviewer comments for a source
    # result classified only TESTED; physical status is the trigger.
    tested = promoted("TESTED")["procedures"][0]
    tested.pop("manual_review_receipt")
    assert verify.audit(full_ledger_with(tested), lookup) == []
