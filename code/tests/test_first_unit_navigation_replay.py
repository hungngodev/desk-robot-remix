"""Guide 90 replay of the existing read-only Guide 60 component boundaries.

Synthetic evidence only: no live detector, navigation executor or physical
arrival is represented by this fixture.
"""

from dataclasses import replace

import pytest
from desk_robot.object_search import SearchViewpoint, propose_object_search
from desk_robot.object_targets import (
    ObjectEvidence,
    ObjectOwner,
    ObjectQuery,
    resolve_object_target,
)
from desk_robot.route_planner import GridSnapshot, RouteRequest, SafetyEnvelope


@pytest.fixture
def navigation_replay():
    query = ObjectQuery(
        "robot-01", "key", "session-2", "turn-7", "origin-3", 8,
        "tag-4", "cal-5", 101, "mac-boot-5", 12, 900_000, 1_500_000,
    )
    owner = ObjectOwner(
        "robot-01", "session-2", "turn-7", "origin-3", 8, "tag-4",
        "cal-5", 101, "mac-boot-5", 12, True, True,
    )
    seen = ObjectEvidence(
        "robot-01", "key", "camera_seen", 1800000000.1,
        receipt_us=950_000, captured_us=940_000, origin_id="origin-3",
        epoch=8, anchor_id="tag-4", calibration_id="cal-5",
        camera_boot=101, host_boot_id="mac-boot-5", camera_grant=12,
        frame_seq=23, floor_mm=(120, 220), projection_qualified=True,
        confidence=0.92,
    )
    grid = GridSnapshot(
        "robot-01", "origin-3", 8, "tag-4", "cal-5", 15, 15, 20,
        ("safe",) * 225, 800_000, 1_400_000, True,
    )
    route = RouteRequest(
        "robot-01", "origin-3", 8, "tag-4", "session-2", "turn-7",
        (3, 7), 0, (9, 7), 1_500_000,
    )
    envelope = SafetyEnvelope(3, 2, 2, 32, True)
    view = SearchViewpoint(
        "robot-01", "origin-3", 8, "tag-4", "cal-5", "view-1",
        (9, 7), 0, True, heading=0,
    )
    return query, owner, seen, grid, route, envelope, view


def plan_replay(fixture, evidence, *, support=None, current=True):
    query, owner, _, grid, route, envelope, view = fixture
    if support is not None:
        grid = replace(grid, support=support)
    target = resolve_object_target(query, owner, evidence, now_us=1_000_000)
    search = propose_object_search(
        grid, route, envelope, query, owner, target, (view,),
        now_us=1_000_000, clock_us=lambda: 1_000_000,
        request_is_current=lambda: current,
    )
    assert target.may_execute is False and target.arrived is False
    assert search.may_execute is False and search.arrived is False
    if search.route is not None:
        assert search.route.may_execute is False
    return target, search


@pytest.mark.parametrize("barrier", [None, "unknown", "unsafe"])
def test_occluded_target_proposal_requires_supported_route(navigation_replay, barrier):
    _, _, seen, grid, _, _, view = navigation_replay
    absent = replace(
        seen, source="camera_not_seen", frame_seq=24, receipt_us=970_000,
        captured_us=960_000, floor_mm=None, projection_qualified=False,
    )
    support = list(grid.support)
    if barrier is not None:
        for y in range(grid.height):
            support[y * grid.width + 7] = barrier
    target, search = plan_replay(
        navigation_replay, [absent, seen], support=tuple(support),
    )
    assert target.status == "last_seen"
    assert target.confirmed_floor_mm is None
    assert target.search_hint_mm == seen.floor_mm
    if barrier is None:
        assert search.status == "viewpoint_proposal"
        assert search.reason == "must_reobserve_target"
        assert search.route is not None
        assert search.route.cells[-1] == view.cell
        assert search.route.final_heading == view.heading
    else:
        assert search.status == "no_current_sighting"
        assert search.route is None


@pytest.mark.parametrize("negative", ["contradiction", "foreign", "low_confidence"])
def test_unqualified_observations_never_propose_a_viewpoint(navigation_replay, negative):
    _, _, seen, _, _, _, _ = navigation_replay
    if negative == "contradiction":
        evidence = [
            seen,
            replace(seen, source="camera_not_seen", floor_mm=None,
                    projection_qualified=False),
        ]
    elif negative == "foreign":
        evidence = [replace(seen, robot_id="robot-02")]
    else:
        evidence = [replace(seen, confidence=0.1)]
    target, search = plan_replay(navigation_replay, evidence)
    assert target.status == "unknown"
    assert target.confirmed_floor_mm is None and target.search_hint_mm is None
    assert search.status == "no_current_sighting"
    assert search.route is None


def test_moved_target_requires_new_sighting_and_never_claims_arrival(navigation_replay):
    _, _, seen, _, _, _, _ = navigation_replay
    absent = replace(
        seen, source="camera_not_seen", frame_seq=24, receipt_us=970_000,
        captured_us=960_000, floor_mm=None, projection_qualified=False,
    )
    _, before = plan_replay(navigation_replay, [seen, absent])
    assert before.status == "viewpoint_proposal"
    moved = replace(
        seen, frame_seq=25, receipt_us=990_000, captured_us=980_000,
        floor_mm=(160, 260),
    )
    target, after = plan_replay(navigation_replay, [moved, absent, seen])
    assert target.status == "current_sighting"
    assert target.confirmed_floor_mm == moved.floor_mm
    assert target.search_hint_mm is None
    assert after.status == "no_current_sighting" and after.route is None
    # The old observation pose is not an approach to the newly seen object.


def test_cancelled_owner_cannot_reuse_resolved_last_seen_target(navigation_replay):
    _, _, seen, _, _, _, _ = navigation_replay
    absent = replace(
        seen, source="camera_not_seen", frame_seq=24, receipt_us=970_000,
        captured_us=960_000, floor_mm=None, projection_qualified=False,
    )
    _, live = plan_replay(navigation_replay, [seen, absent])
    assert live.route is not None
    _, stopped = plan_replay(navigation_replay, [seen, absent], current=False)
    assert stopped.status == "rejected"
    assert stopped.reason == "request_invalidated"
    assert stopped.route is None
