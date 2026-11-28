"""Deterministic operation-count regression for bounded route clearance."""

from dataclasses import replace

import pytest
from desk_robot import route_planner as planner


def fixture(width=80, height=80):
    grid = planner.GridSnapshot(
        "r", "o", 1, "a", "c", width, height, 10,
        ("safe",) * (width * height), 100, 5000, True,
    )
    request = planner.RouteRequest(
        "r", "o", 1, "a", "s", "t", (15, 40), 0, (65, 40), 4000,
    )
    envelope = planner.SafetyEnvelope(100, 0, 0, 120, True)
    return grid, request, envelope


def test_clearance_geometry_work_is_bounded_per_radius(monkeypatch):
    grid, request, envelope = fixture()
    original = planner.math.hypot
    calls = 0

    def counted(*args):
        nonlocal calls
        calls += 1
        return original(*args)

    monkeypatch.setattr(planner.math, "hypot", counted)
    result = planner.plan_route(grid, request, envelope, now_us=1000)
    assert result.status == "planned"
    assert result.cells == tuple((x, 40) for x in range(15, 66))
    assert result.may_execute is False
    # At most one half-width scan per row for each of the two radii.
    assert calls <= 23 * 12 + 27 * 14


@pytest.mark.parametrize("marker", ["unknown", "occupied", "stale", "unsafe"])
@pytest.mark.parametrize("offset", [(0, -1), (0, 1), (-1, 0), (1, 0)])
def test_tangent_cells_are_never_skipped(marker, offset):
    grid, request, _ = fixture()
    x, y = request.start
    dx, dy = offset
    support = list(grid.support)
    support[(y + dy) * grid.width + x + dx] = marker
    grid = replace(grid, support=tuple(support))
    envelope = planner.SafetyEnvelope(5, 0, 0, 5, True)
    result = planner.plan_route(grid, request, envelope, now_us=1000)
    assert result.reason == "unsafe_start"
    assert not result.cells


def test_oversized_simulation_grid_does_not_relax_production_limit():
    grid, request, envelope = fixture(200, 200)
    result = planner.plan_route(grid, request, envelope, now_us=1000)
    assert result.reason == "invalid_grid"
    assert not result.cells
