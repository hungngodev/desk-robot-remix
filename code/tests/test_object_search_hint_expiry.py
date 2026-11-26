"""Historical descriptions must not renew metric search authority."""

from dataclasses import replace

import pytest
from desk_robot.object_targets import (
    MAX_SEARCH_HINT_AGE_US,
    ObjectEvidence,
    ObjectOwner,
    ObjectQuery,
    resolve_object_target,
)


@pytest.fixture
def evidence():
    query = ObjectQuery(
        "robot-01", "key", "session", "turn", "origin", 1, "tag", "cal", 1,
        "host", 1, 30_000_000, 32_000_000,
    )
    owner = ObjectOwner(
        "robot-01", "session", "turn", "origin", 1, "tag", "cal", 1,
        "host", 1, True, True,
    )
    seen = ObjectEvidence(
        "robot-01", "key", "camera_seen", 1800000000.0,
        receipt_us=1_000_000, captured_us=1_000_000, origin_id="origin",
        epoch=1, anchor_id="tag", calibration_id="cal", camera_boot=1,
        host_boot_id="host", camera_grant=1, frame_seq=1,
        floor_mm=(120, 220), projection_qualified=True, confidence=0.95,
    )
    return query, owner, seen


@pytest.mark.parametrize("offset, expected", [(-1, (120, 220)), (0, None), (1, None)])
def test_hint_expires_at_capture_age_boundary(evidence, offset, expected):
    query, owner, seen = evidence
    now_us = seen.captured_us + MAX_SEARCH_HINT_AGE_US + offset
    target = resolve_object_target(query, owner, [seen], now_us=now_us)
    assert target.status == "last_seen"
    assert target.search_hint_mm == expected
    assert target.seen_at_wall_s == seen.seen_at_wall_s
    assert target.confirmed_floor_mm is None and not target.may_execute


@pytest.mark.parametrize(("changes", "now_us"), [
    ({"host_boot_id": "previous-host"}, 30_000_000),
    ({"captured_us": None}, 30_000_000),
    ({"receipt_us": 31_000_000}, 31_000_000),
])
def test_unprovable_age_or_delayed_receipt_cannot_renew_hint(evidence, changes, now_us):
    query, owner, seen = evidence
    target = resolve_object_target(query, owner, [replace(seen, **changes)], now_us=now_us)
    assert target.status == "last_seen"
    assert target.reason == "search_hint_expired"
    assert target.search_hint_mm is None
    assert target.seen_at_wall_s == seen.seen_at_wall_s


def test_new_capture_can_replace_expired_hint(evidence):
    query, owner, seen = evidence
    newer = replace(seen, captured_us=30_000_000, receipt_us=30_000_000,
                    frame_seq=2, floor_mm=(240, 320))
    target = resolve_object_target(query, owner, [seen, newer], now_us=31_000_000)
    assert target.status == "last_seen"
    assert target.search_hint_mm == newer.floor_mm
    assert not target.arrived and not target.may_execute
