"""Real purchasing approval cannot use fake or unscoped trial receipts."""
import importlib.util
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
       + SHA + "/docs/records/one-unit-physical-trials.csv")


def receipt(scope, gate):
    return {
        "result": "pass", "source_sha": SHA, "scope": scope, "gate": gate,
        "reviewer": "real_review_account", "tested_on": "2026-11-18",
        "evidence_url": URL,
    }


def lookup(url):
    assert url.endswith("/contents/docs/records/"
                        "one-unit-physical-trials.csv?ref=" + SHA)
    return {"type": "file", "size": 1000}


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


def test_empty_evidence_fails_closed_even_with_valid_sha():
    errors = release.audit_release({}, SHA, lookup)
    assert errors
    assert "no release receipts recorded" not in errors or len(errors) > 1


def test_clean_exact_sha_required(monkeypatch):
    good = {"sha": SHA, "tracked_clean": True, "root_tree_intact": True}
    monkeypatch.setattr(release, "source_snapshot", lambda: good)
    monkeypatch.setattr(
        release.subprocess, "check_output",
        lambda *args, **kwargs: "impl/mac-hardware-safety-preflight-2026-11-10",
    )
    assert release.checkout_sha() == SHA
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
