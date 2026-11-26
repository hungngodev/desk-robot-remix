"""Synthetic evidence only: a floor hazard is not a movable obstacle."""

from dataclasses import replace

import pytest
from desk_robot.spatial_grid import GridEvidenceError, RangeCellBatch, SpatialGrid

EDGE = (0, 0)
CUP = (1, 0)


def _grid_with_hazards():
    grid = SpatialGrid("robot-01", 7, "odom-1", "tag-4", "cal-5", 2, 1)
    grid.anchored = True
    _record(grid, "floor_unsafe", 0, 1, 1_000_000, (EDGE,))
    _record(grid, "floor_supported", 1, 1, 1_000_000, (CUP,))
    _record(grid, "obstacle_clear", 4, 1, 1_000_000, (EDGE,))
    _record(grid, "obstacle_hit", 5, 1, 1_000_000, (CUP,))
    return grid


def _record(grid, kind, lane, sequence, now, cells):
    batch = RangeCellBatch(
        grid.robot_id, grid.body_boot, grid.origin_id, grid.epoch,
        grid.calibration_id, lane, sequence, now - 900_000, now, kind, cells, True,
    )
    grid.record(batch, now_us=now)
    return batch


def test_expired_cup_can_clear_without_granting_cliff_support():
    grid = _grid_with_hazards()
    assert grid.snapshot(now_us=2_000_000).support == ("unsafe", "occupied")
    now = 2_000_001
    assert grid.snapshot(now_us=now).support == ("stale", "stale")

    # New forward clearance cannot serve as evidence of a desk underneath.
    _record(grid, "obstacle_clear", 4, 2, now, (EDGE, CUP))
    assert grid.snapshot(now_us=now).support == ("stale", "stale")
    assert grid.log_odds(*CUP) == pytest.approx(-0.8)

    # Only fresh, independent downward evidence makes the cup's cell usable.
    _record(grid, "floor_supported", 1, 2, now, (CUP,))
    assert grid.snapshot(now_us=now).support == ("stale", "safe")
    _record(grid, "floor_unsafe", 0, 2, now, (EDGE,))
    assert grid.snapshot(now_us=now).support == ("unsafe", "safe")


@pytest.mark.parametrize("body_boot", [7, 8])
def test_origin_reset_does_not_transfer_old_hazard_coordinates(body_boot):
    grid = _grid_with_hazards()
    old = _record(grid, "floor_unsafe", 0, 2, 1_000_001, (EDGE,))
    grid.invalidate_origin(body_boot, "odom-2")
    now = 1_000_002
    snapshot = grid.snapshot(now_us=now)
    assert not snapshot.anchored
    assert snapshot.support == ("unknown", "unknown")
    assert snapshot.observed_at_us == 0
    with pytest.raises(GridEvidenceError):
        grid.record(replace(old, received_us=now), now_us=now)

    _record(grid, "obstacle_clear", 4, 1, now, (EDGE, CUP))
    assert grid.snapshot(now_us=now).support == ("unknown", "unknown")
    _record(grid, "floor_unsafe", 0, 1, now, (EDGE,))
    _record(grid, "floor_supported", 1, 1, now, (CUP,))
    snapshot = grid.snapshot(now_us=now)
    assert snapshot.support == ("unsafe", "safe")
    assert not snapshot.anchored
