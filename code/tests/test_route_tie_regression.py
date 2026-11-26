"""Deterministic route proposals on cyclic and disconnected support grids."""

from dataclasses import replace

from desk_robot.route_planner import GridSnapshot, RouteRequest, SafetyEnvelope, plan_route


def _fixture():
    rows = (
        ".....#.",
        "..#....",
        "..###.#",
        ".......",
        ".#..#..",
        "......#",
        "#...#.#",
    )
    grid = GridSnapshot(
        "r", "o", 1, "a", "c", 7, 7, 20,
        tuple("safe" if cell == "." else "occupied" for row in rows for cell in row),
        1, 1000, True,
    )
    request = RouteRequest("r", "o", 1, "a", "s", "t", (3, 5), 2, (2, 0), 1000,
                           goal_heading=0)
    return grid, request, SafetyEnvelope(1, 0, 0, 1, True)


def test_equal_weighted_cost_prefers_fewer_turns_deterministically():
    grid, request, envelope = _fixture()
    expected = ((3, 5), (2, 5), (1, 5), (0, 5), (0, 4), (0, 3),
                (0, 2), (0, 1), (0, 0), (1, 0), (2, 0))
    for _ in range(3):
        result = plan_route(grid, request, envelope, now_us=2)
        assert result.status == "planned"
        assert result.cells == expected
        assert len(result.cells) == len(set(result.cells))
        assert result.final_heading == 0
        assert result.may_execute is False


def test_stationary_request_never_moves_and_walled_goal_is_unreachable():
    grid, request, envelope = _fixture()
    stationary = replace(request, goal=request.start, goal_heading=request.heading)
    result = plan_route(grid, stationary, envelope, now_us=2, max_expansions=1)
    assert (result.reason, result.cells, result.may_execute) == (
        "at_observation_pose", (request.start,), False,
    )
    cells = list(grid.support)
    for x, y in ((1, 0), (3, 0), (2, 1)):
        cells[y * grid.width + x] = "occupied"
    result = plan_route(replace(grid, support=tuple(cells)), request, envelope, now_us=2)
    assert (result.status, result.reason, result.cells, result.may_execute) == (
        "rejected", "no_safe_route", (), False,
    )
