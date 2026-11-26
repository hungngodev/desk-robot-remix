"""Cardinal route headings follow the right-handed spatial frame contract."""

import pytest
from desk_robot.route_planner import GridSnapshot, RouteRequest, SafetyEnvelope, plan_route


@pytest.mark.parametrize(
    "heading,delta",
    [(0, (1, 0)), (1, (0, 1)), (2, (-1, 0)), (3, (0, -1))],
)
def test_cardinal_route_heading_matches_map_axes(heading, delta):
    grid = GridSnapshot(
        robot_id="robot-01", origin_id="origin-1", epoch=1,
        anchor_id="tag-1", calibration_id="cal-1", width=15, height=15,
        cell_mm=20, support=("safe",) * 225, observed_at_us=500,
        expires_at_us=4000, anchored=True,
    )
    start = (7, 7)
    goal = (start[0] + delta[0], start[1] + delta[1])
    request = RouteRequest(
        robot_id=grid.robot_id, origin_id=grid.origin_id, epoch=grid.epoch,
        anchor_id=grid.anchor_id, session_id="session-1", turn_id="turn-1",
        start=start, heading=heading, goal=goal, deadline_us=3000,
        goal_heading=heading,
    )
    envelope = SafetyEnvelope(3, 2, 2, 32, True)
    result = plan_route(grid, request, envelope, now_us=1000)
    assert result.status == "planned"
    assert result.cells == (start, goal)
    assert result.final_heading == heading
    assert result.may_execute is False
