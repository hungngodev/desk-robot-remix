"""Guide 50 evidence-only grid tests; no motor or physical anchor."""

from dataclasses import replace

import pytest
from desk_robot.route_planner import RouteRequest, SafetyEnvelope, plan_route
from desk_robot.spatial_grid import RangeCellBatch, SpatialGrid


def batch(kind, lane, seq, *, capture, cells):
    return RangeCellBatch(
        "robot-01", 7, "odom-1", 0, "camera-abc", lane, seq,
        capture, 1_000_000 + capture, kind, cells, True,
    )


@pytest.mark.parametrize("hit_lane", (4, 5, 6, 7))
def test_fresh_hit_overrides_saturated_clearance_and_requires_recovery(hit_lane):
    grid = SpatialGrid("robot-01", 7, "odom-1", "tag-4", "camera-abc", 9, 5)
    corridor = tuple((x, 2) for x in range(1, 8))
    target = ((4, 2),)
    floor = batch("floor_supported", 0, 1, capture=10_000, cells=corridor)
    grid.record(floor, now_us=floor.received_us)
    for seq in range(1, 6):
        clear = batch("obstacle_clear", 4, seq, capture=seq * 10_000, cells=corridor)
        grid.record(clear, now_us=clear.received_us)
    assert grid.state(4, 2, now_us=1_050_000) == "safe"
    assert grid.log_odds(4, 2) == pytest.approx(-4.0)
    request = RouteRequest(
        "robot-01", "odom-1", 0, "tag-4", "session-1", "turn-1",
        (1, 2), 0, (7, 2), 1_500_000,
    )
    envelope = SafetyEnvelope(3, 2, 2, 32, True)

    def propose(now_us):
        # Explicit simulation fixture only: production grid stays unanchored.
        snapshot = grid.to_route_snapshot(now_us=now_us)
        assert not snapshot.anchored
        return plan_route(replace(snapshot, anchored=True), request, envelope, now_us=now_us)

    assert propose(1_050_000).status == "planned"

    hit = batch("obstacle_hit", hit_lane, 6 if hit_lane == 4 else 1,
                capture=60_000, cells=target)
    grid.record(hit, now_us=hit.received_us)
    assert grid.state(4, 2, now_us=hit.received_us) == "occupied"
    assert grid.log_odds(4, 2) == pytest.approx(1.2)
    assert grid.snapshot(now_us=hit.received_us).support[22] == "occupied"
    assert grid.state(3, 2, now_us=hit.received_us) == "safe"
    blocked = propose(hit.received_us)
    assert blocked.reason == "no_safe_route"
    assert blocked.cells == () and not blocked.may_execute
    for seq, expected in ((7, "unknown"), (8, "unknown"), (9, "safe")):
        clear = batch("obstacle_clear", 4, seq, capture=seq * 10_000, cells=target)
        grid.record(clear, now_us=clear.received_us)
        assert grid.state(4, 2, now_us=clear.received_us) == expected
        assert propose(clear.received_us).status == ("planned" if expected == "safe" else "rejected")
