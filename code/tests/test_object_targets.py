"""Offline Guide 60 truthful object target selection and origin fencing."""

from dataclasses import replace

import pytest
from desk_robot.object_targets import (
    ObjectEvidence,
    ObjectOwner,
    ObjectQuery,
    resolve_object_target,
)


def fixtures():
    q = ObjectQuery("robot-01", "key", "session-2", "turn-7", "origin-3", 8,
                    "tag-4", "cal-5", 101, "mac-boot-5", 12, 900_000, 1_500_000)
    owner = ObjectOwner("robot-01", "session-2", "turn-7", "origin-3", 8,
                        "tag-4", "cal-5", 101, "mac-boot-5", 12, True, True)
    seen = ObjectEvidence(
        "robot-01", "key", "camera_seen", 1800000000.1,
        receipt_us=950_000, origin_id="origin-3", epoch=8, anchor_id="tag-4",
        calibration_id="cal-5", camera_boot=101,
        host_boot_id="mac-boot-5", camera_grant=12, frame_seq=23,
        floor_mm=(120, 220), projection_qualified=True, confidence=0.92,
    )
    return q, owner, seen


def resolve(rows=None, query=None, owner=None, *, now_us=1_000_000, **kwargs):
    q, o, seen = fixtures()
    return resolve_object_target(query or q, owner or o,
                                 rows if rows is not None else [seen],
                                 now_us=now_us, **kwargs)


def test_fresh_calibrated_sighting_is_not_an_arrival_or_motor_permit():
    result = resolve()
    assert (result.status, result.reason, result.confirmed_floor_mm) == (
        "current_sighting", "fresh_projected_view", (120, 220))
    assert result.search_hint_mm is None
    assert not result.arrived and not result.may_execute
    assert result.request_fence == fixtures()[0]


def test_fresh_unprojected_view_is_not_a_metric_target():
    _, _, seen = fixtures()
    result = resolve([replace(seen, projection_qualified=False)])
    assert result.status == "current_sighting"
    assert result.reason == "fresh_view_no_metric_projection"
    assert result.confirmed_floor_mm is None
    assert not result.may_execute


def test_stale_key_is_last_seen_hint_not_current_location():
    result = resolve(now_us=1_300_001)
    assert result.status == "last_seen"
    assert result.reason == "historical_sighting_only"
    assert result.confirmed_floor_mm is None
    assert result.search_hint_mm == (120, 220)


def test_latest_camera_not_seen_invalidates_current_sighting_not_memory():
    _, _, seen = fixtures()
    absent = replace(seen, source="camera_not_seen", receipt_us=955_000,
                     frame_seq=24, floor_mm=None, projection_qualified=False)
    result = resolve([seen, absent])
    assert (result.status, result.reason) == ("last_seen", "not_currently_confirmed")
    assert result.confirmed_floor_mm is None
    assert result.search_hint_mm == (120, 220)
    # Later fresh positive can restore current *evidence*, but not arrival.
    newer = replace(seen, receipt_us=970_000, frame_seq=25)
    assert resolve([seen, absent, newer]).status == "current_sighting"


@pytest.mark.parametrize(
    ("positive_seq", "positive_receipt", "negative_seq", "negative_receipt",
     "current"),
    [
        (23, 975_000, 24, 955_000, False),  # Old positive finishes last.
        (25, 955_000, 24, 975_000, True),   # Old negative finishes last.
        (24, 975_000, 24, 955_000, False),  # Contradictory same-frame results.
        (25, 975_000, 24, 955_000, True),   # Genuine new positive restores view.
    ],
)
def test_capture_sequence_overrules_out_of_order_detection_completion(
    positive_seq, positive_receipt, negative_seq, negative_receipt, current,
):
    _, _, seen = fixtures()
    positive = replace(seen, frame_seq=positive_seq,
                       receipt_us=positive_receipt)
    negative = replace(seen, source="camera_not_seen",
                       frame_seq=negative_seq, receipt_us=negative_receipt,
                       floor_mm=None, projection_qualified=False)
    for evidence in ([positive, negative], [negative, positive]):
        result = resolve(evidence)
        assert result.status == ("current_sighting" if current else "last_seen")
        assert result.confirmed_floor_mm == ((120, 220) if current else None)
        assert result.reason == (
            "fresh_projected_view" if current else "not_currently_confirmed"
        )
        assert result.arrived is False and result.may_execute is False


def test_seen_from_an_old_camera_boot_or_origin_is_only_historical():
    _, _, seen = fixtures()
    for e in [replace(seen, camera_boot=100), replace(seen, origin_id="prior")]:
        result = resolve([e])
        assert result.status == "last_seen"
        assert result.confirmed_floor_mm is None
    assert resolve([replace(seen, origin_id="prior")]).search_hint_mm is None


def test_foreign_robot_is_not_queried_even_if_high_confidence():
    _, _, seen = fixtures()
    result = resolve([replace(seen, robot_id="robot-02")])
    assert result.status == "unknown"
    assert result.confirmed_floor_mm is None


@pytest.mark.parametrize(("changed", "reason"), [
    ({"turn_id": "turn-8"}, "turn_or_robot_changed"),
    ({"session_id": "new-session"}, "turn_or_robot_changed"),
    ({"robot_id": "robot-02"}, "turn_or_robot_changed"),
    ({"epoch": 9}, "origin_map_or_camera_changed"),
    ({"origin_id": "picked-up"}, "origin_map_or_camera_changed"),
    ({"calibration_id": "cal-6"}, "origin_map_or_camera_changed"),
    ({"camera_boot": 102}, "origin_map_or_camera_changed"),
    ({"host_boot_id": "mac-boot-6"}, "origin_map_or_camera_changed"),
    ({"camera_grant": 13}, "origin_map_or_camera_changed"),
])
def test_new_turn_origin_or_camera_cancels_prior_request(changed, reason):
    _, owner, _ = fixtures()
    result = resolve(owner=replace(owner, **changed))
    assert result.status == "rejected"
    assert result.reason == reason


def test_cancel_deadline_and_monotonic_rollback_fail_closed():
    q, _, _ = fixtures()
    assert resolve(query=replace(q, cancelled=True)).reason == "cancelled"
    assert resolve(now_us=1_500_000).reason == "deadline_or_clock_invalid"
    assert resolve(now_us=800_000).reason == "deadline_or_clock_invalid"
    assert resolve(query=replace(q, deadline_us=True)).reason == "invalid_request_or_evidence_budget"


def test_consent_revocation_blocks_live_and_private_recall():
    _, owner, _ = fixtures()
    assert resolve(owner=replace(owner, memory_allowed=False)).reason == "memory_consent_revoked"
    result = resolve(owner=replace(owner, camera_allowed=False))
    assert result.status == "last_seen" and result.confirmed_floor_mm is None


def test_newer_user_report_does_not_become_camera_fact_or_metric_goal():
    _, _, seen = fixtures()
    report = ObjectEvidence("robot-01", "key", "user_reported", 1800000001.0)
    result = resolve([replace(seen, receipt_us=100), report])
    assert result.status == "user_reported"
    assert result.source == "user_reported"
    assert result.confirmed_floor_mm is None and result.search_hint_mm is None
    assert not result.may_execute


def test_newer_witnessed_candy_beats_old_user_report():
    q, _, seen = fixtures()
    candy_q = replace(q, label="wrapped candy")
    candy = replace(seen, label="wrapped candy", receipt_us=200_000)
    report = ObjectEvidence("robot-01", "wrapped candy", "user_reported", 1700000000.0)
    result = resolve([candy, report], query=candy_q)
    assert result.status == "last_seen"
    assert result.source == "camera_seen"


def test_future_replayed_low_confidence_and_malformed_predictions_never_confirm():
    _, _, seen = fixtures()
    invalid = [
        replace(seen, receipt_us=2_000_000),
        replace(seen, receipt_us=899_999),
        replace(seen, confidence=0.20),
        replace(seen, confidence=float("nan")),
        replace(seen, floor_mm=(float("inf"), 100)),
        replace(seen, frame_seq=True),
        replace(seen, camera_boot=True),
        replace(seen, projection_qualified="yes"),
    ]
    for candidate in invalid:
        result = resolve([candidate])
        assert result.status != "current_sighting"
        assert result.confirmed_floor_mm is None


def test_unqualified_foreign_or_reported_floor_never_yields_a_route_goal():
    _, _, seen = fixtures()
    unknown = resolve([replace(seen, robot_id="robot-02")])
    assert unknown.status == "unknown"
    report = ObjectEvidence("robot-01", "key", "user_reported", 1800000000.0,
                            floor_mm=(90, 90), projection_qualified=True)
    assert resolve([report]).status == "unknown"


def test_unbounded_result_set_and_untrusted_labels_fail_closed():
    q, _, seen = fixtures()
    assert resolve([seen] * 129).reason == "invalid_request_or_evidence_budget"
    assert resolve(query=replace(q, label="../../etc")).status == "rejected"
    assert resolve([replace(seen, source="motor_arrived")]).status == "unknown"
    assert resolve([replace(seen, confidence=10**1000)]).status == "unknown"


def test_persisted_mac_receipt_is_not_current_after_host_reboot_or_grant_reset():
    _, _, seen = fixtures()
    for replay in (replace(seen, host_boot_id="older-mac-boot"),
                   replace(seen, camera_grant=11)):
        result = resolve([replay])
        assert result.status == "last_seen"
        assert result.confirmed_floor_mm is None
        assert result.arrived is False


def test_malformed_query_is_safe_rejection_not_attribute_error():
    _, owner, seen = fixtures()
    invalid = resolve_object_target(None, owner, [seen], now_us=1_000_000)
    assert invalid.status == "rejected" and not invalid.may_execute


def test_huge_wall_time_and_threshold_do_not_crash_target_resolution():
    _, _, seen = fixtures()
    assert resolve([replace(seen, seen_at_wall_s=10**1000)]).status == "unknown"
    assert resolve(min_confidence=10**1000).status == "rejected"


def test_target_results_bind_exact_request_but_refusals_do_not():
    query, owner, seen = fixtures()
    assert resolve([seen], query=query, owner=owner).request_fence == query
    assert resolve([seen], query=query, owner=owner, now_us=1_300_001).request_fence == query
    denied = resolve([seen], query=query, owner=replace(owner, turn_id="other"))
    assert denied.status == "rejected"
    assert denied.request_fence is None
