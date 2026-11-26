"""DRR-034: diagonal and boundary cells intersecting a pivot's swept disk."""

from dataclasses import replace

import pytest
from desk_robot.route_planner import (
    GridSnapshot,
    RouteRequest,
    SafetyEnvelope,
    plan_route,
    revalidate_route_step,
)


@pytest.mark.parametrize("marker", ["unsafe", "unknown", "occupied", "stale"])
@pytest.mark.parametrize("corner", [(4, 4), (8, 9)])
def test_diagonal_corner_intersection_vetoes_exact_turn(marker, corner):
    grid = GridSnapshot(
        "pet", "origin", 3, "tag", "cal", 15, 15, 20,
        ("safe",) * 225, 500, 4000, True,
    )
    start, goal = (6, 6), (6, 7)
    request = RouteRequest("pet", "origin", 3, "tag", "s", "t", start, 0, goal, 3000)
    envelope = SafetyEnvelope(5, 2, 2, 39, True)
    proposal = plan_route(grid, request, envelope, now_us=1000)
    assert proposal.cells == (start, goal) and not proposal.may_execute

    support = list(grid.support)
    x, y = corner
    support[y * grid.width + x] = marker
    updated = replace(grid, support=tuple(support), observed_at_us=1400)
    # The nearest corner is sqrt(30**2 + 30**2), about 42.43 mm,
    # while the cell center is 56.57 mm away. Each fixture hits just
    # one endpoint's 43 mm disk and neither straight footprint.
    for radius, permitted in ((38, True), (39, False)):
        measured = replace(envelope, swept_turn_radius_mm=radius)
        result = plan_route(updated, request, measured, now_us=1500)
        assert (result.cells == (start, goal)) is permitted
        assert not result.may_execute
        assert revalidate_route_step(
            updated, proposal, measured, start=start, heading=0, goal=goal, now_us=1500,
        ) is permitted


@pytest.mark.parametrize("x", [1, 13])
@pytest.mark.parametrize("heading", [0, 2])
def test_off_map_turn_tangency_is_not_safe_support(x, heading):
    grid = GridSnapshot(
        "pet", "origin", 3, "tag", "cal", 15, 15, 20,
        ("safe",) * 225, 500, 4000, True,
    )
    start, goal = (x, 6), (x, 7)
    request = RouteRequest("pet", "origin", 3, "tag", "s", "t", start, heading, goal, 3000)
    envelope = SafetyEnvelope(5, 2, 2, 25, True)
    proposal = plan_route(grid, request, envelope, now_us=1000)
    assert proposal.cells == (start, goal) and not proposal.may_execute
    tangent = replace(envelope, swept_turn_radius_mm=26)
    assert not revalidate_route_step(
        grid, proposal, tangent, start=start, heading=heading, goal=goal, now_us=1500,
    )
    result = plan_route(grid, request, tangent, now_us=1500)
    assert result.cells != (start, goal) and not result.may_execute
    straight = replace(request, heading=1)
    result = plan_route(grid, straight, tangent, now_us=1500)
    assert result.cells == (start, goal) and not result.may_execute
