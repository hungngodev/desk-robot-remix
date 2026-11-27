"""An old A* proposal never substitutes for fresh per-pulse geometry."""

from dataclasses import replace

import pytest
from desk_robot.route_planner import (
    GridSnapshot,
    RouteRequest,
    SafetyEnvelope,
    plan_route,
    revalidate_route_step,
)


def scenario(*, turning=False):
    grid = GridSnapshot(
        "pet", "origin", 3, "tag", "cal", 15, 15, 20,
        ("safe",) * 225, 500, 4000, True,
    )
    start = (6, 6)
    goal = (6, 7) if turning else (7, 6)
    request = RouteRequest("pet", "origin", 3, "tag", "s", "t", start, 0, goal, 3000)
    envelope = SafetyEnvelope(8, 2, 2, 32, True)
    route = plan_route(grid, request, envelope, now_us=1000)
    assert route.cells == (start, goal) and not route.may_execute
    return grid, route, envelope, start, goal


def check(grid, route, envelope, start, goal, **kwargs):
    return revalidate_route_step(
        grid, route, envelope, start=start, goal=goal, heading=0,
        now_us=kwargs.pop("now_us", 1500), **kwargs,
    )


@pytest.mark.parametrize("marker", ["unknown", "stale", "unsafe", "occupied"])
@pytest.mark.parametrize("turning", [False, True])
def test_live_inflated_or_swept_neighbor_vetoes_old_route(marker, turning):
    grid, route, envelope, start, goal = scenario(turning=turning)
    assert check(grid, route, envelope, start, goal)
    support = list(grid.support)
    # Both centers remain safe; the changed cell intersects only the margin
    # (straight) or the larger swept turn disk (turning).
    x, y = (4, 6) if turning else (7, 5)
    support[y * grid.width + x] = marker
    updated = replace(grid, support=tuple(support), observed_at_us=1400)
    assert updated.support[start[1] * grid.width + start[0]] == "safe"
    assert updated.support[goal[1] * grid.width + goal[0]] == "safe"
    assert not check(updated, route, envelope, start, goal)


@pytest.mark.parametrize("change", [
    {"epoch": 4}, {"origin_id": "other"}, {"anchor_id": "other"},
    {"calibration_id": "other"}, {"robot_id": "other"}, {"anchored": False},
    {"observed_at_us": 499}, {"expires_at_us": 1500},
])
def test_step_rejects_invalidated_or_rolled_back_snapshot(change):
    grid, route, envelope, start, goal = scenario()
    assert not check(replace(grid, **change), route, envelope, start, goal)


def test_refreshed_map_never_extends_original_proposal_deadline():
    grid, route, envelope, start, goal = scenario()
    updated = replace(grid, observed_at_us=2900, expires_at_us=6000)
    assert check(updated, route, envelope, start, goal, now_us=2999)
    assert not check(updated, route, envelope, start, goal, now_us=3000)
    assert not check(updated, route, envelope, start, goal, now_us=2999,
                     clock_us=lambda: 3000)


def test_no_unproposed_edge_or_invented_detour():
    grid, route, envelope, start, goal = scenario()
    assert not check(grid, route, envelope, start, (6, 7))
    assert not check(grid, route, envelope, goal, start)
    assert check(grid, route, envelope, goal, goal)


def fixture(goal=(6, 7)):
    grid = GridSnapshot('pet', 'origin', 3, 'tag', 'cal', 15, 15, 20,
                        ('safe',) * 225, 500, 4000, True)
    request = RouteRequest('pet', 'origin', 3, 'tag', 's', 't',
                           (6, 6), 0, goal, 5000)
    return grid, request


def unknown(grid, cell):
    support = list(grid.support)
    support[cell[1] * grid.width + cell[0]] = 'unknown'
    return replace(grid, support=tuple(support), observed_at_us=1400)


@pytest.mark.parametrize('cell', [(4, 6), (6, 9)])
def test_swept_turn_endpoint_requires_both_margins(cell):
    grid, request = fixture()
    envelope = SafetyEnvelope(5, 2, 2, 27, True)
    route = plan_route(grid, request, envelope, now_us=1000)
    assert route.cells == (request.start, request.goal)
    assert revalidate_route_step(grid, route, envelope, start=request.start,
                                 heading=0, goal=request.goal, now_us=1500)
    assert not revalidate_route_step(unknown(grid, cell), route, envelope,
                                     start=request.start, heading=0,
                                     goal=request.goal, now_us=1500)


def test_tangential_unknown_cell_is_blocked():
    grid, request = fixture(goal=(7, 6))
    envelope = SafetyEnvelope(6, 2, 2, 27, True)
    assert plan_route(grid, request, envelope, now_us=1500).status == 'planned'
    result = plan_route(unknown(grid, (6, 5)), request, envelope, now_us=1500)
    assert (result.status, result.reason, result.cells, result.may_execute) == (
        'rejected', 'unsafe_start', (), False)


def test_map_expiry_during_search_precedes_request_deadline():
    grid, request = fixture(goal=(8, 6))
    envelope = SafetyEnvelope(5, 2, 2, 27, True)
    samples = iter((1000, 4000))
    result = plan_route(grid, request, envelope, now_us=1000,
                        clock_us=lambda: next(samples, 4000))
    assert (result.status, result.reason, result.cells, result.may_execute) == (
        'rejected', 'deadline_or_map_expired', (), False)


@pytest.mark.parametrize("cell", [(8, 6), (3, 6)])
def test_turn_margin_west_heading_vetoes_swept_offset_cells(cell):
    """Turn into west move checks lateral turn-clearance cells along the swept arc."""
    grid = GridSnapshot(
        "pet", "origin", 3, "tag", "cal", 15, 15, 20,
        ("safe",) * 225, 500, 4000, True,
    )
    start, goal = (6, 6), (5, 6)
    envelope = SafetyEnvelope(5, 2, 2, 27, True)
    request = RouteRequest("pet", "origin", 3, "tag", "s", "t", start, 1, goal, 3000)
    route = plan_route(grid, request, envelope, now_us=1000)
    assert route.cells == (start, goal) and not route.may_execute
    assert revalidate_route_step(
        grid, route, envelope, start=start, goal=goal, heading=1, now_us=1500,
    )

    support = list(grid.support)
    support[cell[1] * grid.width + cell[0]] = "unknown"
    updated = replace(grid, support=tuple(support), observed_at_us=1400)
    assert not revalidate_route_step(
        updated, route, envelope, start=start, goal=goal, heading=1, now_us=1500,
    )
