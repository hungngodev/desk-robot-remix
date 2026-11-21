"""Real purchasing approval cannot use fake or unscoped trial receipts."""
import base64
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "code/scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location(
    "test_procurement_evidence", SCRIPTS / "verify_procurement_receipts.py"
)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)

SHA = "a" * 40
URL = ("https://github.com/hungngodev/desk-robot-remix/blob/"
       + SHA + "/docs/records/release-evidence.json")


def receipt(scope, gate):
    return {
        "record_id": scope + ":" + gate,
        "result": "pass", "source_sha": SHA, "scope": scope, "gate": gate,
        "reviewer": "real_review_account", "tested_on": "2026-11-18",
        "device_revision": "inspected_rev_A",
        "measurement": {"observed": "trial for " + scope + "." + gate},
        "evidence_url": URL,
    }


def lookup(url, records=None):
    assert url.endswith("/contents/docs/records/"
                        "release-evidence.json?ref=" + SHA)
    if records is None:
        records = [receipt("part:imu", gate) for gate in release.PART_GATES]
        records += [receipt("system", gate) for gate in release.SYSTEM_GATES]
        records.append(receipt("system", release.FIRST_ROBOT_ROOM_GATE))
        for ident in release.SUPPLEMENTAL_DECISIONS:
            scope = "supplemental:" + ident
            records += [
                receipt(scope, "decision_receipt"),
                receipt(scope, "alternative_or_parent_receipt"),
            ]
    raw = json.dumps({"receipts": records}).encode("utf-8")
    return {
        "type": "file", "size": len(raw), "encoding": "base64",
        "content": base64.b64encode(raw).decode("ascii"),
    }


def test_scoped_immutable_actual_records_are_required():
    data = {
        "parts": {
            "imu": {gate: receipt("part:imu", gate)
                    for gate in release.PART_GATES},
        },
        "room_pod": {},
        "system": {gate: receipt("system", gate)
                   for gate in release.SYSTEM_GATES},
        "supplemental_decisions": {
            ident: {"disposition": "rejected_in_favor_of_qualified_alternative",
                    "decision_receipt": receipt("supplemental:" + ident,
                                                "decision_receipt"),
                    "alternative_or_parent_receipt": receipt(
                        "supplemental:" + ident,
                        "alternative_or_parent_receipt")}
            for ident in release.SUPPLEMENTAL_DECISIONS
        },
    }
    assert release.audit_release(data, SHA, lookup) == []
    data["parts"]["imu"][release.PART_GATES[0]]["scope"] = "part:other"
    assert any("un pinned" in e.replace("unpinned", "un pinned")
               for e in release.audit_release(data, SHA, lookup))


@pytest.mark.parametrize("mutated", [
    {"source_sha": "b" * 40},
    {"scope": "part:someone_else"},
    {"gate": "unrelated_gate"},
    {"reviewer": "fixture"},
    {"evidence_url": "https://example.org/looks-real"},
])
def test_release_receipt_rejects_fake_sha_scope_and_origin(mutated):
    evidence = {"parts": {"imu": {
        gate: receipt("part:imu", gate) for gate in release.PART_GATES
    }}}
    evidence["parts"]["imu"][release.PART_GATES[0]].update(mutated)
    errors = release.audit_release(evidence, SHA, lookup)
    assert errors


@pytest.mark.parametrize("changed", [
    {"scope": "part:foreign"},
    {"gate": "unrelated_gate"},
    {"source_sha": "b" * 40},
    {"reviewer": "forged_reviewer"},
    {"tested_on": "2026-11-19"},
    {"device_revision": "another_board"},
    {"record_id": "foreign_receipt"},
    {"measurement": {"observed": "invented trial"}},
])
def test_immutable_scoped_source_rejects_forged_local_claim(changed):
    gate = release.PART_GATES[0]
    original = receipt("part:imu", gate)
    assert release.verified_scoped_record(original, SHA, lookup)
    assert not release.verified_scoped_record(
        {**original, **changed}, SHA, lookup
    )


@pytest.mark.parametrize("tested_on", [
    "2026-02-30", "20261118", "tomorrow", "",
    True, None, "2026-11-18T10:00:00",
])
def test_physical_receipt_requires_canonical_completed_calendar_day(tested_on):
    gate = release.PART_GATES[0]
    invalid = {**receipt("part:imu", gate), "tested_on": tested_on}
    def source(url):
        return lookup(url, records=[invalid])

    assert not release.verified_scoped_record(invalid, SHA, source)
    errors = release.audit_release(
        {"parts": {"imu": {gate: invalid}}}, SHA, source,
    )
    assert any("unpinned or generic signoff" in error for error in errors)


def test_future_physical_trial_cannot_release_even_with_matching_immutable_json():
    from datetime import date, timedelta

    gate = release.PART_GATES[0]
    future = {**receipt("part:imu", gate),
              "tested_on": (date.today() + timedelta(days=1)).isoformat()}
    assert not release.verified_scoped_record(
        future, SHA, lambda url: lookup(url, records=[future]),
    )
    errors = release.audit_release(
        {"parts": {"imu": {gate: future}}}, SHA,
        lambda url: lookup(url, records=[future]),
    )
    assert any("unpinned or generic signoff" in error for error in errors)


def test_real_prior_leap_day_can_be_verified_against_matching_immutable_record():
    gate = release.PART_GATES[0]
    prior = {**receipt("part:imu", gate), "tested_on": "2024-02-29"}
    assert release.verified_scoped_record(
        prior, SHA, lambda url: lookup(url, records=[prior]),
    )


def test_pinned_procurement_json_rejects_ambiguous_duplicate_receipt_fields():
    gate = release.PART_GATES[0]
    item = receipt("part:imu", gate)
    captured = []
    def capture(source_url):
        response = lookup(source_url, records=[item])
        captured.append(response)
        return response

    # Exercise the real immutable URL conversion before corrupting the
    # returned JSON. The public evidence_url is not itself the GitHub API.
    assert release.verified_scoped_record(item, SHA, capture)
    good = captured[0]
    raw = base64.b64decode(good["content"]).decode()
    for changed in (
        raw.replace('"result": "pass"',
                    '"result": "fail", "result": "pass"'),
        raw.replace('"observed": "trial', '"observed": NaN, "observed": "trial'),
    ):
        data = changed.encode()
        response = {**good, "size": len(data),
                    "content": base64.b64encode(data).decode()}
        assert not release.verified_scoped_record(
            item, SHA, lambda _, payload=response: payload,
        )


def test_common_physical_json_receipt_decoder_rejects_nonfinite_and_duplicates():
    from verify_playbook_receipts import (
        finite_receipt_float,
        reject_nonfinite_receipt_value,
        strict_receipt_object,
    )
    for malformed in (
        '{"result":"fail","result":"pass"}',
        '{"measurement":{"x":NaN}}',
        '{"measurement":{"x":Infinity}}',
        '{"measurement":{"x":1e9999}}',
        '{"measurement":{"x":-1e9999}}',
    ):
        with pytest.raises(ValueError):
            json.loads(malformed, object_pairs_hook=strict_receipt_object,
                       parse_constant=reject_nonfinite_receipt_value,
                       parse_float=finite_receipt_float)


def test_immutable_procurement_record_rejects_exponent_overflow():
    gate = release.PART_GATES[0]
    claimed = receipt("part:imu", gate)
    claimed["measurement"] = {"lift_mm": float("inf")}
    # The local claim and source would compare equal as infinity without
    # checking parsed float finiteness at the immutable JSON boundary.
    raw = json.dumps({"receipts": [claimed]}).replace(
        "Infinity", "1e9999",
    ).encode("utf-8")
    response = {
        "type": "file", "size": len(raw), "encoding": "base64",
        "content": base64.b64encode(raw).decode("ascii"),
    }
    assert not release.verified_scoped_record(
        claimed, SHA, lambda _: response,
    )


def test_existing_file_without_claim_cannot_release_purchase():
    gate = release.PART_GATES[0]
    original = receipt("part:imu", gate)

    def unrelated(url):
        return lookup(url, records=[receipt("part:unrelated", gate)])

    assert not release.verified_scoped_record(original, SHA, unrelated)
    errors = release.audit_release(
        {"parts": {"imu": {gate: original}}}, SHA, unrelated,
    )
    assert any("immutable scoped record" in error for error in errors)


def test_duplicate_and_missing_measurement_records_fail_closed():
    gate = release.PART_GATES[0]
    original = receipt("part:imu", gate)
    for records in (
        [original, original],
        [dict(original, measurement={})],
        [dict(original, record_id="")],
    ):
        assert not release.verified_scoped_record(
            original, SHA, lambda url, records=records: lookup(url, records)
        )


@pytest.mark.parametrize("broken", [
    {"parts": []},
    {"parts": {"imu": None}},
    {"room_pod": {"scd40": "not a receipt mapping"}},
    {"system": []},
    {"supplemental_decisions": False},
    {"supplemental_decisions": {"power_path": None}},
])
def test_malformed_physical_release_sections_fail_closed_without_network(broken):
    def forbidden_network(_):
        raise AssertionError("Bad JSON envelope must fail before network")

    errors = release.audit_release(broken, SHA, forbidden_network)
    assert any("malformed" in problem for problem in errors)


@pytest.mark.parametrize("sha", [None, 123, True, [], {}])
def test_nonstring_purchase_revision_is_rejected_not_a_regex_crash(sha):
    errors = release.audit_release({}, sha, lambda _: 1 / 0)
    assert errors == ["missing exact checkout SHA or release evidence"]


def test_github_contents_directory_cannot_be_a_physical_receipt():
    item = receipt("part:imu", release.PART_GATES[0])
    for not_file in ([], None, "unexpected", {"type": "dir"}, 42):
        assert not release.verified_scoped_record(
            item, SHA, lambda _, body=not_file: body
        )


def test_empty_evidence_fails_closed_even_with_valid_sha():
    errors = release.audit_release({}, SHA, lookup)
    assert errors
    assert "no release receipts recorded" not in errors or len(errors) > 1


def live_pr_at(sha=SHA):
    return {
        "number": 17, "state": "open", "draft": True,
        "head": {
            "sha": sha, "ref": "impl/mac-hardware-safety-preflight-2026-11-10",
            "repo": {"full_name": "hungngodev/desk-robot-remix"},
        },
        "base": {"repo": {"full_name": "hungngodev/desk-robot-remix"}},
    }


def test_clean_exact_sha_required(monkeypatch):
    good = {"sha": SHA, "tracked_clean": True, "root_tree_intact": True}
    monkeypatch.setattr(release, "source_snapshot", lambda: good)
    monkeypatch.setattr(
        release.subprocess, "check_output",
        lambda *args, **kwargs: "impl/mac-hardware-safety-preflight-2026-11-10",
    )
    assert release.checkout_sha(lookup=lambda _: live_pr_at()) == SHA
    for bad in (
        {**good, "tracked_clean": False},
        {**good, "root_tree_intact": False},
        {**good, "sha": "bad"},
        {**good, "sha": None},
    ):
        monkeypatch.setattr(release, "source_snapshot",
                            lambda bad=bad: bad)
        with pytest.raises(ValueError, match="clean exact commit"):
            release.checkout_sha()


@pytest.mark.parametrize("change", [
    ("number", 18), ("state", "closed"), ("draft", False),
    ("head_sha", "b" * 40), ("head_ref", "other"),
    ("head_repo", "other/project"), ("base_repo", "other/project"),
])
def test_purchase_source_refuses_stale_or_foreign_live_pr(
    monkeypatch, change,
):
    good = {"sha": SHA, "tracked_clean": True, "root_tree_intact": True}
    monkeypatch.setattr(release, "source_snapshot", lambda: good)
    monkeypatch.setattr(
        release.subprocess, "check_output",
        lambda *args, **kwargs: "impl/mac-hardware-safety-preflight-2026-11-10",
    )
    key, value = change
    pr = live_pr_at()
    if key == "head_sha":
        pr["head"]["sha"] = value
    elif key == "head_ref":
        pr["head"]["ref"] = value
    elif key == "head_repo":
        pr["head"]["repo"]["full_name"] = value
    elif key == "base_repo":
        pr["base"]["repo"]["full_name"] = value
    else:
        pr[key] = value
    with pytest.raises(ValueError, match="live draft PR #17"):
        release.checkout_sha(lookup=lambda _: pr)


def test_live_pr_network_unavailable_holds_purchasing(monkeypatch):
    from urllib.error import URLError

    monkeypatch.setattr(
        release, "source_snapshot",
        lambda: {"sha": SHA, "tracked_clean": True, "root_tree_intact": True},
    )
    monkeypatch.setattr(
        release.subprocess, "check_output",
        lambda *args, **kwargs: "impl/mac-hardware-safety-preflight-2026-11-10",
    )

    def offline(_):
        raise URLError("network inaccessible")

    with pytest.raises(ValueError, match="Cannot verify live PR #17"):
        release.checkout_sha(lookup=offline)
    with pytest.raises(ValueError, match="Invalid live PR #17"):
        release.checkout_sha(lookup=lambda _: [])


def test_live_network_failure_cannot_qualify_fake_record():
    from urllib.error import URLError

    evidence = {"parts": {"imu": {
        gate: receipt("part:imu", gate) for gate in release.PART_GATES
    }}}
    def offline(_):
        raise URLError("offline")
    errors = release.audit_release(evidence, SHA, offline)
    assert any("record lookup unavailable" in error for error in errors)


def test_first_robot_uses_first_observer_not_completed_five_robot_fleet():
    station = {
        gate: receipt("system", gate)
        for gate in release.SYSTEM_GATES
        if gate not in release.FLEET_ONLY_SYSTEM_GATES
    }
    station[release.FIRST_ROBOT_ROOM_GATE] = receipt(
        "system", release.FIRST_ROBOT_ROOM_GATE
    )
    decisions = {
        ident: {
            "disposition": "rejected_in_favor_of_qualified_alternative",
            "decision_receipt": receipt("supplemental:" + ident,
                                        "decision_receipt"),
            "alternative_or_parent_receipt": receipt(
                "supplemental:" + ident, "alternative_or_parent_receipt"),
        }
        for ident in release.SUPPLEMENTAL_DECISIONS
    }
    evidence = {
        "system": station, "supplemental_decisions": decisions,
        "parts": {"imu": {gate: receipt("part:imu", gate)
                           for gate in release.PART_GATES}},
    }
    assert release.audit_release(evidence, SHA, lookup, first_robot=True) == []
    assert any("missing receipt" in msg
               for msg in release.audit_release(evidence, SHA, lookup))
    del station["protected_1s_charger_and_dock_contacts"]
    assert any("protected_1s_charger_and_dock_contacts" in msg
               for msg in release.audit_release(
                   evidence, SHA, lookup, first_robot=True))


def test_purchase_approval_refuses_foreign_or_detached_branch(monkeypatch):
    good = {"sha": SHA, "tracked_clean": True, "root_tree_intact": True}
    monkeypatch.setattr(release, "source_snapshot", lambda: good)
    for branch in ("main", "other/experiment", ""):
        monkeypatch.setattr(
            release.subprocess, "check_output",
            lambda *args, label=branch, **kwargs: label,
        )
        with pytest.raises(ValueError, match="canonical PR #17 branch"):
            release.checkout_sha()
