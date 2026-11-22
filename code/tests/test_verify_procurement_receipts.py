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


def measurement_for_gate(scope, gate):
    if gate in release.CRITICAL_TRIAL_GATES:
        specification = release.CRITICAL_TRIAL_GATES[gate]
        quantities = []
        for name, unit, lower, upper, _ in specification["quantities"]:
            quantities.append({
                "name": name, "unit": unit,
                "value": 1 if name in release.POSITIVE_CLEARANCE_METRICS
                else lower,
                "minimum": 0, "maximum": upper if upper is not None
                else max(10, lower),
            })
        return {
            "sample_count": specification["minimum_samples"],
            "conditions": {
                "setup": "installed_test_fixture",
                "instrument": "calibrated_measurement_tool",
                "installed_hardware": "revision_A_assembled_robot",
                "procedure_revision": "physical_acceptance_v1",
            },
            "quantities": quantities,
        }
    if gate in release.PHYSICAL_GATE_METRICS:
        metric, unit = release.PHYSICAL_GATE_METRICS[gate]
        return {
            "sample_count": 3,
            "conditions": {"setup": "installed_bench_fixture",
                           "instrument": "calibrated_meter"},
            "quantities": [{"name": metric, "unit": unit,
                            "value": 5.0, "minimum": 0.0, "maximum": 10.0}],
        }
    return {"observed": "trial for " + scope + "." + gate}


def receipt(scope, gate):
    return {
        "record_id": scope + ":" + gate,
        "result": "pass", "source_sha": SHA, "scope": scope, "gate": gate,
        "reviewer": "real_review_account", "tested_on": "2026-11-18",
        "device_revision": "inspected_rev_A",
        "measurement": measurement_for_gate(scope, gate),
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
        '{"measurement":{"x":1e-9999}}',
        '{"measurement":{"x":-1e-9999}}',
        '{"measurement":{"x":1.0000000000000001}}',
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


@pytest.mark.parametrize("replacement", [True, 1.0])
def test_procurement_nested_measurement_type_confusion_never_releases(replacement):
    """JSON true and 1, or 1.0 and 1, cannot impersonate immutable millimeters."""
    import copy

    gate = release.PART_GATES[0]
    recorded = receipt("part:imu", gate)
    recorded["measurement"] = {
        "lift": {"lift_mm": 1, "samples_mm": [3, {"width_mm": 2}]}
    }
    claimed = copy.deepcopy(recorded)
    claimed["measurement"]["lift"]["lift_mm"] = replacement

    def source(url):
        return lookup(url, records=[recorded])

    assert release.verified_scoped_record(recorded, SHA, source)
    assert not release.verified_scoped_record(claimed, SHA, source)
    errors = release.audit_release(
        {"parts": {"imu": {gate: claimed}}}, SHA, source,
    )
    assert any("immutable scoped record absent or mismatched" in err
               and f"part:imu.{gate}" in err for err in errors)


def test_procurement_nested_list_boolean_cannot_impersonate_sample_count():
    import copy

    gate = release.PART_GATES[0]
    recorded = receipt("part:imu", gate)
    recorded["measurement"] = {"trials": [{"count": 1}, {"count": 2}]}
    forged = copy.deepcopy(recorded)
    forged["measurement"]["trials"][0]["count"] = True
    assert release.verified_scoped_record(
        recorded, SHA, lambda url: lookup(url, records=[recorded])
    )
    assert not release.verified_scoped_record(
        forged, SHA, lambda url: lookup(url, records=[recorded])
    )


@pytest.mark.parametrize(("token", "claimed"), [
    ("1e-9999", 0.0),
    ("-1e-9999", -0.0),
    ("1.0000000000000001", 1.0),
])
def test_procurement_immutable_measurement_refuses_lossy_numeric_source(
    token, claimed,
):
    gate = release.PART_GATES[0]
    item = receipt("part:imu", gate)
    item["measurement"] = {"measured_current_a": claimed}
    # Without strict parsing the immutable raw source and local claim compare
    # equal even though they contain different numeric measurements.
    baseline = json.dumps({"receipts": [item]})
    original = json.dumps(claimed)
    raw = baseline.replace(
        '"measured_current_a": ' + original,
        '"measured_current_a": ' + token,
    ).encode("utf-8")
    assert raw != baseline.encode("utf-8")
    payload = {
        "type": "file", "size": len(raw), "encoding": "base64",
        "content": base64.b64encode(raw).decode("ascii"),
    }
    assert not release.verified_scoped_record(
        item, SHA, lambda _: payload,
    )


@pytest.mark.parametrize("valid", ["0.0", "-0.0", "0.125", "1e-8", "1.0"])
def test_finite_decimal_receipt_floats_still_decode(valid):
    from verify_playbook_receipts import (
        finite_receipt_float,
        strict_receipt_object,
    )
    decoded = json.loads(
        '{"measurement":{"x":' + valid + '}}',
        object_pairs_hook=strict_receipt_object,
        parse_float=finite_receipt_float,
    )
    assert decoded["measurement"]["x"] == float(valid)

def test_reviewed_default_station_deferrals_need_no_immutable_purchase_receipts():
    deferred = frozenset({"room_amg8833", "room_nfc_game_tokens"})
    decisions = {
        ident: {
            "disposition": "rejected_in_favor_of_qualified_alternative",
            "decision_receipt": receipt("supplemental:" + ident,
                                        "decision_receipt"),
            "alternative_or_parent_receipt": receipt(
                "supplemental:" + ident, "alternative_or_parent_receipt"),
        }
        for ident in release.SUPPLEMENTAL_DECISIONS if ident not in deferred
    }
    evidence = {
        "system": {gate: receipt("system", gate)
                   for gate in release.SYSTEM_GATES},
        "supplemental_decisions": decisions,
    }
    assert release.audit_release(
        evidence, SHA, lookup, deferred_optional_ids=deferred
    ) == []
    # Without the generator's reviewed disposition the same omissions
    # cannot silently pass the online immutable receipt verifier.
    errors = release.audit_release(evidence, SHA, lookup)
    assert any("room_amg8833" in problem for problem in errors)
    assert any("room_nfc_game_tokens" in problem for problem in errors)

    evidence["supplemental_decisions"]["room_amg8833"] = {
        "disposition": "selected",
    }
    assert "deferred optional has conflicting purchase evidence" in (
        release.audit_release(
            evidence, SHA, lookup, deferred_optional_ids=deferred
        )
    )
    assert "invalid deferred optional receipt scope" in (
        release.audit_release(
            evidence, SHA, lookup,
            deferred_optional_ids=frozenset({"bq24075_charger_candidate"}),
        )
    )


def test_selected_station_option_still_needs_every_physical_gate_receipt():
    selected = "room_amg8833"
    deferred = frozenset({"room_nfc_game_tokens"})
    decisions = {
        ident: {
            "disposition": "rejected_in_favor_of_qualified_alternative",
            "decision_receipt": receipt("supplemental:" + ident,
                                        "decision_receipt"),
            "alternative_or_parent_receipt": receipt(
                "supplemental:" + ident, "alternative_or_parent_receipt"),
        }
        for ident in release.SUPPLEMENTAL_DECISIONS
        if ident not in deferred and ident != selected
    }
    scope = "supplemental:" + selected
    decisions[selected] = {
        "disposition": "selected",
        "decision_receipt": receipt(scope, "decision_receipt"),
        **{gate: receipt(scope, gate) for gate in release.PART_GATES},
    }
    evidence = {
        "system": {gate: receipt("system", gate)
                   for gate in release.SYSTEM_GATES},
        "supplemental_decisions": decisions,
    }
    sourced = [claim for _, _, claim in release.required_receipts(
        evidence, deferred_optional_ids=deferred
    )]
    assert release.audit_release(
        evidence, SHA, lambda url: lookup(url, records=sourced),
        deferred_optional_ids=deferred,
    ) == []
    del decisions[selected][release.PART_GATES[0]]
    errors = release.audit_release(
        evidence, SHA, lambda url: lookup(url, records=sourced),
        deferred_optional_ids=deferred,
    )
    assert any(scope in problem and "missing receipt" in problem
               for problem in errors)


def test_first_robot_accepts_pinned_stronger_fleet_station_receipt():
    deferred = frozenset({"room_amg8833", "room_nfc_game_tokens"})
    fleet_gate = "room_pod_usb_serial_and_five_pet_observers"
    first_gate = release.FIRST_ROBOT_ROOM_GATE
    system = {
        gate: receipt("system", gate) for gate in release.SYSTEM_GATES
        if gate not in release.FLEET_ONLY_SYSTEM_GATES
    }
    system[fleet_gate] = receipt("system", fleet_gate)
    decisions = {
        ident: {
            "disposition": "rejected_in_favor_of_qualified_alternative",
            "decision_receipt": receipt("supplemental:" + ident,
                                        "decision_receipt"),
            "alternative_or_parent_receipt": receipt(
                "supplemental:" + ident, "alternative_or_parent_receipt"),
        }
        for ident in release.SUPPLEMENTAL_DECISIONS if ident not in deferred
    }
    evidence = {"system": system, "supplemental_decisions": decisions}
    chosen = [gate for scope, gate, _ in release.required_receipts(
        evidence, first_robot=True, deferred_optional_ids=deferred,
    ) if scope == "system"]
    assert fleet_gate in chosen
    assert first_gate not in chosen
    assert release.audit_release(
        evidence, SHA, lookup, first_robot=True,
        deferred_optional_ids=deferred,
    ) == []

    # Its own original gate and immutable provenance are required.
    system[fleet_gate] = receipt("system", first_gate)
    assert any(fleet_gate in error and "unpinned or generic signoff" in error
               for error in release.audit_release(
                   evidence, SHA, lookup, first_robot=True,
                   deferred_optional_ids=deferred,
               ))
    system[fleet_gate] = receipt("system", fleet_gate)
    system[first_gate] = receipt("system", first_gate)
    chosen = [gate for scope, gate, _ in release.required_receipts(
        evidence, first_robot=True, deferred_optional_ids=deferred,
    ) if scope == "system"]
    assert first_gate in chosen
    assert fleet_gate not in chosen
    assert release.audit_release(
        evidence, SHA, lookup, first_robot=True,
        deferred_optional_ids=deferred,
    ) == []
    del system[first_gate]
    del system[fleet_gate]
    assert any(first_gate in error and "missing receipt" in error
               for error in release.audit_release(
                   evidence, SHA, lookup, first_robot=True,
                   deferred_optional_ids=deferred,
               ))


def test_purchase_ci_verifies_every_named_job_from_same_exact_run_attempt():
    run_url = (
        "https://github.com/hungngodev/desk-robot-remix/actions/runs/12345"
    )
    api = "https://api.github.com/repos/hungngodev/desk-robot-remix"
    run = {
        "id": 12345, "run_attempt": 2, "head_sha": SHA,
        "name": "Host verification", "event": "pull_request",
        "head_branch": "impl/mac-hardware-safety-preflight-2026-11-10",
        "head_repository": {"full_name": "hungngodev/desk-robot-remix"},
        "path": ".github/workflows/host-verification.yml",
        "status": "completed", "conclusion": "success",
    }
    jobs = [
        {
            "id": index + 1, "name": name, "run_id": 12345,
            "run_attempt": 2, "head_sha": SHA,
            "status": "completed", "conclusion": "success",
        }
        for index, name in enumerate(sorted(release.REQUIRED_PURCHASE_CI_JOBS))
    ]

    def check(run_values, job_values, total=None):
        def lookup_ci(url):
            if url == api + "/actions/runs/12345":
                return run_values
            if url == api + "/actions/runs/12345/jobs?per_page=100":
                return {
                    "total_count": len(job_values) if total is None else total,
                    "jobs": job_values,
                }
            raise AssertionError("Unexpected CI API URL: " + url)

        return release.verified_required_ci_jobs(run_url, SHA, lookup_ci)

    assert check(run, jobs)
    assert not check(run, jobs[:-1])
    assert not check(run, jobs, total=6)
    assert not check(run, jobs + [jobs[0]])
    for field, value in (
        ("conclusion", "cancelled"), ("conclusion", "failed"),
        ("conclusion", "skipped"), ("conclusion", None),
        ("status", "queued"), ("status", "in_progress"),
        ("run_id", 12346), ("run_attempt", 1),
        ("head_sha", "b" * 40),
    ):
        altered = [{**job} for job in jobs]
        altered[0][field] = value
        assert not check(run, altered), field
    for field, value in (
        ("conclusion", "cancelled"), ("status", "in_progress"),
        ("event", "push"), ("head_sha", "b" * 40),
        ("name", "Unrelated workflow"), ("run_attempt", 1.0),
        ("path", ".github/workflows/another.yml"),
        ("id", 12346),
    ):
        assert not check({**run, field: value}, jobs), field
    assert not release.verified_required_ci_jobs(None, SHA, lambda _: run)
    assert not release.verified_required_ci_jobs(run_url, "b" * 40,
                                                  lambda _: run)
    from urllib.error import URLError
    assert not release.verified_required_ci_jobs(
        run_url, SHA, lambda _: (_ for _ in ()).throw(URLError("offline"))
    )


@pytest.mark.parametrize("gate", sorted(release.PHYSICAL_GATE_METRICS))
def test_critical_physical_receipt_needs_bounded_actual_measurement(gate):
    original = receipt("system", gate)
    assert release.verified_scoped_record(
        original, SHA, lambda url: lookup(url, records=[original]),
    )
    measurement = original["measurement"]
    observed = measurement["quantities"][0]
    variants = [
        {"observed": "pass, see bench notes"},
        {**measurement, "sample_count": True},
        {**measurement, "sample_count": 0},
        {**measurement, "conditions": {"setup": "bench"}},
        {**measurement, "conditions": {
            "setup": "bench", "instrument": "unknown",
        }},
        {**measurement, "quantities": []},
        {**measurement, "quantities": [
            {**observed, "name": "unrelated_metric"},
        ]},
        {**measurement, "quantities": [
            {**observed, "unit": "wrong_unit"},
        ]},
        {**measurement, "quantities": [
            {**observed, "value": 11.0},
        ]},
        {**measurement, "quantities": [
            {**observed, "minimum": 10.0, "maximum": 0.0},
        ]},
        {**measurement, "quantities": [
            {**observed, "value": True},
        ]},
        {**measurement, "quantities": [
            {**observed, "value": 10**1000},
        ]},
        {**measurement, "quantities": [
            {**observed, "value": -(10**1000)},
        ]},
        {**measurement, "quantities": [
            {**observed, "minimum": -(10**1000)},
        ]},
        {**measurement, "quantities": [
            {**observed, "maximum": 10**1000},
        ]},
    ]
    for changed in variants:
        falsified = {**original, "measurement": changed}
        def source(url, row=falsified):
            return lookup(url, records=[row])
        assert not release.verified_scoped_record(falsified, SHA, source)
        errors = release.audit_release(
            {"system": {gate: falsified}}, SHA, source,
        )
        assert any("system." + gate in error and "unpinned" in error
                   for error in errors)


def test_documentary_decision_does_not_require_physical_instrument():
    record = receipt("supplemental:room_amg8833", "decision_receipt")
    assert release.verified_scoped_record(
        record, SHA, lambda url: lookup(url, records=[record]),
    )


def test_parser_to_audit_release_huge_integer_fails_closed():
    gate = "loaded_drive_and_stopping"
    metric, unit = release.PHYSICAL_GATE_METRICS[gate]
    huge_positive_str = "1" + "0" * 1000
    huge_negative_str = "-1" + "0" * 1000
    for huge_val_str in (huge_positive_str, huge_negative_str):
        raw_json = f"""
        {{
            "record_id": "system:{gate}",
            "result": "pass",
            "source_sha": "{SHA}",
            "scope": "system",
            "gate": "{gate}",
            "reviewer": "real_review_account",
            "tested_on": "2026-11-18",
            "device_revision": "inspected_rev_A",
            "evidence_url": "{URL}",
            "measurement": {{
                "sample_count": 3,
                "conditions": {{"setup": "bench_stop", "instrument": "meter_laser"}},
                "quantities": [
                    {{
                        "name": "{metric}",
                        "unit": "{unit}",
                        "value": {huge_val_str},
                        "minimum": 0,
                        "maximum": 1000000
                    }}
                ]
            }}
        }}
        """
        parsed_receipt = json.loads(raw_json)

        def source(url, row=parsed_receipt):
            return lookup(url, records=[row])

        assert not release.verified_scoped_record(parsed_receipt, SHA, source)
        errors = release.audit_release(
            {"system": {gate: parsed_receipt}}, SHA, source,
        )
        assert any(f"system.{gate}" in err and "unpinned" in err for err in errors)



@pytest.mark.parametrize("gate", sorted(release.CRITICAL_TRIAL_GATES))
def test_critical_product_trial_requires_actual_metric_scope_and_counts(gate):
    """A text-only signed receipt cannot become an A2, A4, A5 or dock pass."""
    import copy

    original = receipt("system", gate)
    assert release.verified_scoped_record(
        original, SHA, lambda url: lookup(url, records=[original]),
    )
    measurement = original["measurement"]
    observations = measurement["quantities"]
    missing = copy.deepcopy(measurement)
    missing["quantities"].pop()
    wrong_unit = copy.deepcopy(measurement)
    wrong_unit["quantities"][0]["unit"] = "unknown"
    wrong_name = copy.deepcopy(measurement)
    wrong_name["quantities"][0]["name"] = "generic_pass"
    under_limit = copy.deepcopy(measurement)
    under_limit["quantities"][0]["value"] = -1
    boolean_count = copy.deepcopy(measurement)
    boolean_count["quantities"][0]["value"] = True
    duplicate = copy.deepcopy(measurement)
    duplicate["quantities"].append(copy.deepcopy(observations[0]))
    unhashable_name = copy.deepcopy(measurement)
    unhashable_name["quantities"][0]["name"] = ["forged"]
    bad_conditions = copy.deepcopy(measurement)
    bad_conditions["conditions"]["procedure_revision"] = "tbd"
    variants = (
        {"result": "pass"},
        {**measurement, "sample_count": (
            release.CRITICAL_TRIAL_GATES[gate]["minimum_samples"] - 1)},
        {**measurement, "sample_count": True},
        missing, wrong_unit, wrong_name, under_limit, boolean_count,
        duplicate, unhashable_name, bad_conditions,
    )
    for changed in variants:
        falsified = {**original, "measurement": changed}
        def source(url, row=falsified):
            return lookup(url, records=[row])
        assert not release.verified_scoped_record(falsified, SHA, source)
        errors = release.audit_release(
            {"system": {gate: falsified}}, SHA, source,
        )
        assert any(
            f"system.{gate}" in error and "unpinned" in error
            for error in errors
        )


@pytest.mark.parametrize("gate,metric", [
    ("sense_speaker_mic_double_talk", "audible_stops_within_500ms"),
    ("sense_speaker_mic_double_talk", "new_intents_retained"),
    ("lift_and_grip_calibration", "flat_key_unassisted_successes"),
    ("lift_and_grip_calibration", "wrapped_candy_unassisted_successes"),
])
def test_critical_trial_rejects_below_published_success_threshold(gate, metric):
    case = receipt("system", gate)
    data = case["measurement"]
    selected = next(item for item in data["quantities"]
                    if item["name"] == metric)
    selected["value"] -= 1
    assert not release.verified_scoped_record(
        case, SHA, lambda url: lookup(url, records=[case]),
    )


def test_critical_dock_requires_both_switches_and_three_ir_viewpoints():
    case = receipt("system", "real_dual_ir_terminal_docking")
    for missing in (
        "left_ir_observed_trials", "center_ir_observed_trials",
        "right_ir_observed_trials", "both_seat_switches_confirmed_trials",
        "unpowered_contact_alignment_error_mm",
    ):
        altered = json.loads(json.dumps(case))
        altered["measurement"]["quantities"] = [
            item for item in altered["measurement"]["quantities"]
            if item["name"] != missing
        ]
        assert not release.verified_scoped_record(
            altered, SHA, lambda url, row=altered: lookup(url, records=[row]),
        )


@pytest.mark.parametrize("gate", [
    "cliff_sensor_mount_height_and_stopping_geometry",
    "four_floor_sensor_reverse_pivot_arc_sweep",
])
def test_cliff_geometry_and_reverse_pivot_need_every_measured_dimension(gate):
    """An immutable generic physical signoff cannot replace installed geometry."""
    import copy

    record = receipt("system", gate)
    assert release.verified_scoped_record(
        record, SHA, lambda url: lookup(url, records=[record]),
    )
    for name, *_ in release.CRITICAL_TRIAL_GATES[gate]["quantities"]:
        missing = copy.deepcopy(record)
        missing["measurement"]["quantities"] = [
            item for item in missing["measurement"]["quantities"]
            if item["name"] != name
        ]
        assert not release.verified_scoped_record(
            missing, SHA, lambda url, row=missing: lookup(url, records=[row]),
        )
    text_only = {**record, "measurement": {"observed": "safe to drive"}}
    assert not release.verified_scoped_record(
        text_only, SHA, lambda url: lookup(url, records=[text_only]),
    )


@pytest.mark.parametrize(("gate", "metric"), [
    ("four_cliff_sensor_surface_trials", "minimum_stopping_margin_mm"),
    ("cliff_sensor_mount_height_and_stopping_geometry", "installed_optical_height_mm"),
    ("cliff_sensor_mount_height_and_stopping_geometry", "minimum_edge_stop_margin_mm"),
    ("four_floor_sensor_reverse_pivot_arc_sweep",
     "minimum_reverse_pivot_stopping_margin_mm"),
])
def test_zero_cliff_clearance_does_not_qualify_a_physical_gate(gate, metric):
    record = receipt("system", gate)
    selected = next(
        item for item in record["measurement"]["quantities"]
        if item["name"] == metric
    )
    selected["value"] = 0
    assert not release.verified_scoped_record(
        record, SHA, lambda url: lookup(url, records=[record]),
    )


def test_surface_sensor_pairs_need_eight_distinct_trials_not_four():
    record = receipt("system", "four_cliff_sensor_surface_trials")
    assert release.verified_scoped_record(
        record, SHA, lambda url: lookup(url, records=[record]),
    )
    insufficient = {**record, "measurement": {
        **record["measurement"], "sample_count": 4,
    }}
    assert not release.verified_scoped_record(
        insufficient, SHA,
        lambda url: lookup(url, records=[insufficient]),
    )
