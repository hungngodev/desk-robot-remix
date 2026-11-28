"""Guide 90 replay of the existing read-only Guide 60 component boundaries.

Synthetic evidence only: no live detector, navigation executor or physical
arrival is represented by this fixture.
"""

import asyncio
from dataclasses import replace

import pytest
from desk_robot.controller import Coordinator
from desk_robot.object_search import SearchViewpoint, propose_object_search
from desk_robot.object_targets import (
    ObjectEvidence,
    ObjectOwner,
    ObjectQuery,
    resolve_object_target,
)
from desk_robot.route_planner import (
    GridSnapshot,
    RouteRequest,
    SafetyEnvelope,
    plan_route,
    revalidate_route_step,
)
from desk_robot.simulator import SimulatedHead, SimulationVision
from desk_robot.spatial_grid import RangeCellBatch, SpatialGrid


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


@pytest.mark.parametrize("fault_at", [1, 2])
async def test_exploration_local_disarm_overrides_host_at_drive_dispatch(
    settings, fault_at,
):
    """A local command rejection wins even after a successful host health read."""
    for robot in settings.robots:
        robot.motor_backend = "stepper_28byj48"
    head = SimulatedHead("robot-01")
    coordinator = Coordinator(
        settings, {"robot-01": head, "robot-02": SimulatedHead("robot-02")},
        SimulationVision(),
    )
    original_command = head.command
    attempts = 0
    accepted = 0
    start = tuple(head.position)

    async def command_with_local_fault(command):
        nonlocal attempts, accepted
        if command.startswith("drive "):
            attempts += 1
            if attempts == fault_at:
                # The host already observed healthy status. Only the local
                # simulated actuator sees this disarm at command admission.
                assert head.armed
                head.armed = False
            receipt = await original_command(command)
            accepted += 1
            return receipt
        return await original_command(command)

    head.command = command_with_local_fault
    try:
        await coordinator.operator_arm("robot-01")
        job = coordinator.explore("robot-01")
        await asyncio.wait_for(coordinator.tasks[job.id], timeout=4)
        assert job.state == "failed"
        assert "Body disarmed" in job.error
        assert job.result is None
        assert attempts == fault_at
        assert accepted == fault_at - 1
        assert tuple(head.position) == (start[0], start[1] - 10 * accepted)
        assert head.commands.count("arm") == 1
        assert head.commands[-1] == "halt"
        assert not head.armed
        assert "robot-01" not in coordinator.permits
        assert any("stop acknowledged" in event for event in job.events)
    finally:
        await coordinator.close()


@pytest.mark.parametrize(
    "scenario,expected_reason,expect_route",
    [
        ("stale_capture", "historical_sighting_only", True),
        ("pre_request", "historical_sighting_only", True),
        ("retired_map", "historical_sighting_only", False),
        ("out_of_order", "not_currently_confirmed", True),
    ],
)
def test_replay_enforces_freshness_pre_request_map_identity_and_frame_order(
    navigation_replay, scenario, expected_reason, expect_route,
):
    query, owner, seen, grid, route, envelope, view = navigation_replay
    if scenario == "stale_capture":
        query = replace(query, created_us=600_000)
        evidence = [replace(seen, captured_us=700_000, receipt_us=990_000)]
    elif scenario == "pre_request":
        evidence = [replace(seen, captured_us=890_000, receipt_us=950_000)]
    elif scenario == "retired_map":
        evidence = [replace(seen, anchor_id="tag-retired")]
    else:
        absent = replace(
            seen, source="camera_not_seen", frame_seq=24, receipt_us=970_000,
            captured_us=960_000, floor_mm=None, projection_qualified=False,
        )
        stale_frame_late_receipt = replace(
            seen, frame_seq=23, receipt_us=990_000, captured_us=980_000,
        )
        evidence = [absent, stale_frame_late_receipt]

    fixture = (query, owner, seen, grid, route, envelope, view)
    target, search = plan_replay(fixture, evidence)
    assert target.status == "last_seen"
    assert target.reason == expected_reason
    assert target.confirmed_floor_mm is None
    if scenario == "retired_map":
        assert target.search_hint_mm is None
        assert search.status == "no_current_sighting"
        assert search.reason == "no_same_map_last_seen_hint"
        assert search.route is None
    else:
        assert target.search_hint_mm == seen.floor_mm
        assert expect_route is True
        assert search.status == "viewpoint_proposal"
        assert search.route is not None
        assert search.route.may_execute is False


def test_unanchoring_grid_after_valid_sighting_revokes_viewpoint_route(
    navigation_replay,
):
    query, owner, seen, grid, route, envelope, view = navigation_replay
    absent = replace(
        seen, source="camera_not_seen", frame_seq=24, receipt_us=970_000,
        captured_us=960_000, floor_mm=None, projection_qualified=False,
    )
    _, before = plan_replay(navigation_replay, [seen, absent])
    assert before.status == "viewpoint_proposal" and before.route is not None

    unanchored_grid = replace(grid, anchored=False)
    _, after = plan_replay(
        (query, owner, seen, unanchored_grid, route, envelope, view),
        [seen, absent],
    )
    assert after.status == "rejected"
    assert after.reason == "unanchored_or_stale_map"
    assert after.route is None


@pytest.mark.parametrize("kind,lane,expected", [
    ("floor_unsafe", 0, "unsafe"),
    ("obstacle_hit", 4, "occupied"),
])
def test_live_range_corner_revokes_previously_safe_route_edge(kind, lane, expected):
    """A new corner hazard invalidates a turn, even when both centers stay safe."""
    grid = SpatialGrid("robot-01", 1, "origin-3", "tag-4", "cal-5", 15, 15, epoch=8)
    grid.anchored = True  # Synthetic qualified map, not a hardware attestation.
    cells = tuple((x, y) for y in range(15) for x in range(15))

    def record(kind, lane, sequence, now, cells):
        grid.record(RangeCellBatch(
            "robot-01", 1, "origin-3", 8, "cal-5", lane, sequence,
            now - 900_000, now, kind, cells, True,
        ), now_us=now)

    record("floor_supported", 0, 1, 1_000_000, cells)
    # Saturated free evidence must not mask a single fresh obstacle hit.
    for sequence in range(1, 6):
        record("obstacle_clear", 4, sequence, 1_000_000 + sequence, cells)
    request = RouteRequest(
        "robot-01", "origin-3", 8, "tag-4", "session-2", "turn-7",
        (3, 7), 0, (9, 9), 2_500_000,
    )
    envelope = SafetyEnvelope(3, 2, 2, 32, True)
    before = grid.to_route_snapshot(now_us=1_000_010)
    route = plan_route(before, request, envelope, now_us=1_000_010)
    assert route.status == "planned" and route.may_execute is False
    assert route.cells[-3:] == ((9, 7), (9, 8), (9, 9))
    assert revalidate_route_step(
        before, route, envelope, start=(8, 7), heading=0, goal=(9, 7),
        now_us=1_000_010,
    )
    assert revalidate_route_step(
        before, route, envelope, start=(9, 7), heading=0, goal=(9, 8),
        now_us=1_000_010,
    )

    now = 1_100_000
    hazard = (10, 8)  # Outside translation clearance, inside swept turn clearance.
    record(kind, lane, 6, now, (hazard,))
    live = grid.to_route_snapshot(now_us=now)
    assert live.anchored and now < route.valid_until_us
    assert grid.state(*hazard, now_us=now) == expected
    assert grid.state(9, 7, now_us=now) == grid.state(9, 8, now_us=now) == "safe"
    assert not revalidate_route_step(
        live, route, envelope, start=(9, 7), heading=0, goal=(9, 8), now_us=now,
    )
    # At the old route's exact expiry, even the previously clear edge is invalid.
    expired = grid.to_route_snapshot(now_us=route.valid_until_us)
    assert not revalidate_route_step(
        expired, route, envelope, start=(8, 7), heading=0, goal=(9, 7),
        now_us=route.valid_until_us,
    )


def test_fresh_snapshot_cannot_replan_over_stale_turn_corner():
    """Refreshing surrounding cells must not renew an unobserved corner."""
    grid = SpatialGrid("robot-01", 1, "origin-3", "tag-4", "cal-5", 15, 15, epoch=8)
    grid.anchored = True
    corner = (10, 8)
    cells = tuple((x, y) for y in range(15) for x in range(15))
    now = 2_000_001
    for sequence, at, observed in (
        (1, 1_000_000, cells),
        (2, now, tuple(cell for cell in cells if cell != corner)),
    ):
        for lane, kind in ((0, "floor_supported"), (4, "obstacle_clear")):
            grid.record(RangeCellBatch(
                "robot-01", 1, "origin-3", 8, "cal-5", lane, sequence,
                at - 900_000, at, kind, observed, True,
            ), now_us=at)
    snapshot = grid.to_route_snapshot(now_us=now)
    assert snapshot.anchored and snapshot.observed_at_us == now < snapshot.expires_at_us
    assert grid.state(*corner, now_us=now) == "stale"
    assert grid.state(9, 7, now_us=now) == grid.state(9, 8, now_us=now) == "safe"
    request = RouteRequest(
        "robot-01", "origin-3", 8, "tag-4", "session-2", "turn-8",
        (9, 7), 0, (9, 8), 2_500_000,
    )
    envelope = SafetyEnvelope(3, 2, 2, 32, True)
    result = plan_route(snapshot, request, envelope, now_us=now)
    assert result.status == "rejected" and result.reason == "no_safe_route"
    assert result.cells == () and result.may_execute is False
    # With the corner genuinely reobserved, the exact same request is viable.
    for lane, kind in ((0, "floor_supported"), (4, "obstacle_clear")):
        grid.record(RangeCellBatch(
            "robot-01", 1, "origin-3", 8, "cal-5", lane, 3,
            now + 1 - 900_000, now + 1, kind, (corner,), True,
        ), now_us=now + 1)
    fresh = plan_route(grid.to_route_snapshot(now_us=now + 1), request, envelope, now_us=now + 1)
    assert fresh.status == "planned" and fresh.cells == ((9, 7), (9, 8))


def test_replay_boundary_guards_and_unanchored_grid_veto(navigation_replay):
    """Exercise capture age, pre-request bound, retired anchor, frame order, and unanchored grid."""
    query, owner, seen, grid, route, envelope, view = navigation_replay
    query_old = replace(query, created_us=600_000)
    stale_capture = replace(seen, captured_us=700_000, receipt_us=990_000)
    t_stale = resolve_object_target(query_old, owner, [stale_capture], now_us=1_000_000)
    s_stale = propose_object_search(
        grid, route, envelope, query_old, owner, t_stale, (view,), now_us=1_000_000,
        clock_us=lambda: 1_000_000, request_is_current=lambda: True,
    )
    assert t_stale.status == "last_seen" and t_stale.confirmed_floor_mm is None
    assert t_stale.search_hint_mm == seen.floor_mm and s_stale.route is not None

    pre_request = replace(seen, captured_us=890_000, receipt_us=990_000)
    t_pre, _ = plan_replay(navigation_replay, [pre_request])
    assert t_pre.status == "last_seen" and t_pre.confirmed_floor_mm is None

    retired_anchor = replace(seen, anchor_id="tag-retired", receipt_us=990_000)
    t_ret, _ = plan_replay(navigation_replay, [retired_anchor])
    assert t_ret.status == "last_seen"
    assert t_ret.confirmed_floor_mm is None and t_ret.search_hint_mm is None

    absent_24 = replace(
        seen, source="camera_not_seen", frame_seq=24, receipt_us=970_000,
        captured_us=960_000, floor_mm=None, projection_qualified=False,
    )
    late_frame_23 = replace(seen, frame_seq=23, receipt_us=990_000, captured_us=940_000)
    t_order, s_order = plan_replay(navigation_replay, [absent_24, late_frame_23])
    assert t_order.status == "last_seen" and t_order.confirmed_floor_mm is None
    assert s_order.status == "viewpoint_proposal"

    unanchored = replace(grid, anchored=False)
    unanchored_search = propose_object_search(
        unanchored, route, envelope, query_old, owner, t_stale, (view,),
        now_us=1_000_000, clock_us=lambda: 1_000_000, request_is_current=lambda: True,
    )
    assert unanchored_search.status == "rejected"
    assert unanchored_search.route is None and unanchored_search.may_execute is False
