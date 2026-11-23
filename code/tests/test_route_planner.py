"""Offline Guide 60 route proposals: no head, motor, camera, or network calls."""

from dataclasses import replace

import pytest
from desk_robot import route_planner as planner
from desk_robot.route_planner import (
    GridSnapshot,
    RouteRequest,
    SafetyEnvelope,
    plan_route,
)


def fixtures():
    grid = GridSnapshot(
        robot_id="robot-01", origin_id="body-boot-7", epoch=3,
        anchor_id="tag-8", calibration_id="cal-2", width=15, height=15,
        cell_mm=20, support=("safe",) * 225,
        observed_at_us=500, expires_at_us=4000, anchored=True,
    )
    request = RouteRequest(
        robot_id="robot-01", origin_id="body-boot-7", epoch=3,
        anchor_id="tag-8", session_id="session-9", turn_id="turn-10",
        start=(3, 7), heading=0, goal=(9, 7), deadline_us=3000,
    )
    envelope = SafetyEnvelope(footprint_radius_mm=3, localization_error_mm=2,
                              stopping_margin_mm=2, swept_turn_radius_mm=32,
                              geometry_qualified=True)
    return grid, request, envelope


def route(grid=None, request=None, envelope=None, *, now_us=1000, **kwargs):
    g, r, e = fixtures()
    return plan_route(grid or g, request or r, envelope or e, now_us=now_us, **kwargs)


def test_straight_supported_corridor_is_deterministic_readonly_proposal():
    first = route()
    assert first.status == "planned"
    assert first.cells == tuple((x, 7) for x in range(3, 10))
    assert first.robot_id == "robot-01"
    assert (first.origin_id, first.epoch, first.session_id, first.turn_id) == (
        "body-boot-7", 3, "session-9", "turn-10")
    assert first.may_execute is False
    assert route() == first


def test_unknown_or_occupied_support_divides_map_even_with_open_space_elsewhere():
    g, r, e = fixtures()
    for marker in ("unknown", "occupied", "stale", "unsafe"):
        cells = list(g.support)
        for y in range(g.height):
            cells[y * g.width + 7] = marker
        actual = route(grid=replace(g, support=tuple(cells)))
        assert actual.status == "rejected"
        assert actual.reason == "no_safe_route"
        assert actual.cells == ()
        assert actual.may_execute is False


def test_narrow_corner_rejects_unmeasured_swept_turn():
    g, r, e = fixtures()
    cells = ["unknown"] * len(g.support)
    for x in range(2, 8):
        cells[7 * g.width + x] = "safe"
    for y in range(7, 11):
        cells[y * g.width + 7] = "safe"
    narrow = replace(g, support=tuple(cells))
    bent = replace(r, start=(3, 7), goal=(7, 10))
    assert route(grid=narrow, request=bent, envelope=e).reason == "no_safe_route"
    # Straight travel on an isolated safe corridor is still a valid read-only proposal.
    assert route(grid=narrow, request=replace(bent, goal=(6, 7)), envelope=e).status == "planned"


@pytest.mark.parametrize(("changed", "reason"), [
    ({"robot_id": "robot-02"}, "robot_mismatch"),
    ({"origin_id": "body-boot-8"}, "map_epoch_changed"),
    ({"epoch": 4}, "map_epoch_changed"),
    ({"anchor_id": "tag-9"}, "map_epoch_changed"),
    ({"cancelled": True}, "cancelled"),
    ({"deadline_us": 999}, "deadline_expired"),
])
def test_stale_cross_robot_cancelled_request_produces_no_path(changed, reason):
    _, r, _ = fixtures()
    actual = route(request=replace(r, **changed))
    assert (actual.status, actual.reason, actual.cells, actual.may_execute) == (
        "rejected", reason, (), False)


@pytest.mark.parametrize(("changed", "reason"), [
    ({"anchored": False}, "unanchored_or_stale_map"),
    ({"expires_at_us": 999}, "unanchored_or_stale_map"),
    ({"observed_at_us": 2000}, "unanchored_or_stale_map"),
    ({"calibration_id": ""}, "invalid_identity"),
    ({"cell_mm": 0}, "invalid_grid"),
    ({"support": ("safe",) * 224}, "invalid_grid"),
])
def test_bad_or_stale_map_is_rejected(changed, reason):
    g, _, _ = fixtures()
    actual = route(grid=replace(g, **changed))
    assert actual.reason == reason and actual.cells == ()


@pytest.mark.parametrize(("observed_at_us", "expires_at_us"), [
    (-1, 4000),
    (0, 4000),
    (500, 10_000_501),
    (500, 10**18),
])
def test_invalid_or_unbounded_map_receipt_never_proposes_a_route(
    observed_at_us, expires_at_us,
):
    grid, _, _ = fixtures()
    result = route(grid=replace(grid, observed_at_us=observed_at_us,
                                expires_at_us=expires_at_us))
    assert result.reason == "unanchored_or_stale_map"
    assert result.status == "rejected"
    assert result.cells == () and result.may_execute is False


def test_maximum_producer_map_lifetime_remains_readonly():
    grid, _, _ = fixtures()
    result = route(grid=replace(grid, observed_at_us=500,
                                expires_at_us=10_000_500))
    assert result.status == "planned"
    assert result.may_execute is False


def test_inflated_footprint_near_off_map_unknown_and_unsafe_goal():
    g, r, e = fixtures()
    e = replace(e, footprint_radius_mm=14)
    assert route(request=replace(r, start=(0, 7)), envelope=e).reason == "unsafe_start"
    assert route(request=replace(r, goal=(14, 7)), envelope=e).reason == "unsafe_goal"
    cells = list(g.support)
    cells[7 * g.width + 9] = "unknown"
    assert route(grid=replace(g, support=tuple(cells))).reason == "unsafe_goal"


def test_unqualified_geometry_and_insufficient_swept_radius_fail_closed():
    _, _, e = fixtures()
    assert route(envelope=replace(e, geometry_qualified=False)).reason == "unqualified_clearance"
    assert route(envelope=replace(e, swept_turn_radius_mm=2)).reason == "unqualified_clearance"
    assert route(envelope=replace(e, stopping_margin_mm=True)).reason == "unqualified_clearance"


def test_monotonic_deadline_and_expansion_budget_remain_finite():
    assert route(max_expansions=1).reason == "search_budget_exhausted"
    assert route(clock_us=lambda: 3000).reason == "deadline_or_map_expired"
    assert route(clock_us=lambda: -1).reason == "invalid_clock"
    assert route(max_expansions=0).reason == "invalid_budget"


def test_goal_with_current_pose_is_not_physical_arrival():
    _, r, _ = fixtures()
    result = route(request=replace(r, goal=r.start))
    assert result.status == "planned"
    assert result.reason == "at_observation_pose"
    assert result.may_execute is False
    assert result.cells == (r.start,)


def test_no_autonomous_reverse_or_blind_spin_for_behind_goal():
    g, r, e = fixtures()
    # Narrow straight aisle has no room to turn around; directly moving
    # backward would be shorter but is explicitly not part of this planner.
    cells = ["unknown"] * len(g.support)
    for x in range(2, 12):
        cells[7 * g.width + x] = "safe"
    narrow = replace(g, support=tuple(cells))
    behind = replace(r, start=(9, 7), goal=(3, 7), heading=0)
    assert route(grid=narrow, request=behind, envelope=e).reason == "no_safe_route"


def test_version_and_live_generation_cancel_are_bounded():
    g, r, _ = fixtures()
    assert route(grid=replace(g, schema_version=2)).reason == "unsupported_schema"
    assert route(request=replace(r, schema_version=2)).reason == "unsupported_schema"
    calls = 0

    def cancel_after_first_expansion():
        nonlocal calls
        calls += 1
        return calls < 2

    stopped = route(request_is_current=cancel_after_first_expansion)
    assert stopped.reason == "request_invalidated"
    assert stopped.cells == () and stopped.may_execute is False
    assert route(request_is_current=lambda: False).reason == "request_invalidated"


def test_same_cell_is_not_a_stale_or_cancelled_arrival():
    _, r, _ = fixtures()
    same = replace(r, goal=r.start)
    assert route(request=same, request_is_current=lambda: False).reason == "request_invalidated"
    assert route(request=same, clock_us=lambda: 3000).reason == "deadline_or_map_expired"


def test_clearance_budget_rejects_unbounded_tiny_cells():
    g, _, e = fixtures()
    tiny = replace(g, cell_mm=1)
    result = route(grid=tiny, envelope=replace(e, swept_turn_radius_mm=400))
    assert result.reason == "unqualified_clearance"


def test_unhashable_untrusted_support_sample_is_finite_refusal():
    g, _, _ = fixtures()
    bad = replace(g, support=(["unsafe"],) + g.support[1:])
    assert route(grid=bad).reason == "invalid_grid"


def test_monotonic_clock_rollback_invalidates_an_inflight_proposal():
    sampled = [1600, 1500]
    result = route(clock_us=lambda: sampled.pop(0) if sampled else 1500)
    assert result.status == "rejected"
    assert result.reason == "invalid_clock"
    assert result.cells == () and result.may_execute is False

def test_same_pose_request_revoked_during_clearance_cannot_be_planned():
    grid, request, _ = fixtures()
    current = True

    class RevokingSupport(tuple):
        def __getitem__(self, index):
            nonlocal current
            current = False
            return super().__getitem__(index)

    result = route(
        grid=replace(grid, support=RevokingSupport(grid.support)),
        request=replace(request, goal=request.start),
        request_is_current=lambda: current,
    )
    assert result.status == "rejected"
    assert result.reason == "request_invalidated"
    assert result.cells == () and result.may_execute is False


def test_goal_pop_after_deadline_cannot_produce_an_obsolete_route(monkeypatch):
    _, request, _ = fixtures()
    clock = 1000
    original_pop = planner.heapq.heappop

    def expire_on_goal_pop(queue):
        nonlocal clock
        item = original_pop(queue)
        if (item[3], item[4]) == request.goal:
            clock = request.deadline_us
        return item

    monkeypatch.setattr(planner.heapq, "heappop", expire_on_goal_pop)
    result = route(clock_us=lambda: clock)
    assert result.status == "rejected"
    assert result.reason == "deadline_or_map_expired"
    assert result.cells == () and result.may_execute is False
