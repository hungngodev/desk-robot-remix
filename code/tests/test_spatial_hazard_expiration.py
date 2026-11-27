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


@pytest.mark.parametrize("body_boot", [7, 8])
def test_relocalized_stable_anchor_preserves_cliff_border_while_cup_decays(body_boot):
    grid = _grid_with_hazards()
    assert grid.snapshot(now_us=1_500_000).support == ("unsafe", "occupied")

    # Unverified reset must fail closed instead of reusing old cell coordinates.
    grid.invalidate_origin(body_boot, "odom-2")
    assert not grid.anchored
    assert grid.snapshot(now_us=1_500_001).support == ("unknown", "unknown")

    # Relocalizing onto a different anchor or calibration must not transfer borders.
    grid.relocalize_anchor("tag-other", "cal-5")
    assert grid.snapshot(now_us=1_500_002).support == ("unknown", "unknown")
    grid.relocalize_anchor("tag-4", "cal-other")
    assert grid.snapshot(now_us=1_500_003).support == ("unknown", "unknown")

    # Verified relocalization onto the same stable anchor + calibration restores
    # only the cliff border; movable-cup occupancy stays cleared.
    grid.relocalize_anchor("tag-4", "cal-5")
    now = 3_500_000
    relocalized = grid.snapshot(now_us=now)
    assert relocalized.anchored
    assert relocalized.support == ("unsafe", "unknown")
    assert grid.log_odds(*CUP) == 0.0

    # Forward clearance still cannot clear the remembered cliff border.
    _record(grid, "obstacle_clear", 4, 1, now, (EDGE, CUP))
    assert grid.snapshot(now_us=now).support == ("unsafe", "unknown")
    _record(grid, "floor_supported", 1, 1, now, (CUP,))
    assert grid.snapshot(now_us=now).support == ("unsafe", "safe")


def test_spatial_runtime_reset_relocalizes_cliff_border_without_cup_occupancy(tmp_path):
    from types import SimpleNamespace

    from desk_robot.memory import MemoryStore
    from desk_robot.route_planner import SafetyEnvelope
    from desk_robot.spatial_frames import PlanarTransform
    from desk_robot.spatial_runtime import SpatialRuntime

    robot_id = "robot-01"
    settings = SimpleNamespace(robots=[SimpleNamespace(id=robot_id)])
    runtime = SpatialRuntime(settings, MemoryStore(tmp_path, [robot_id]))
    envelope = SafetyEnvelope(3, 2, 2, 15, True)
    grid = runtime.bind_qualified_grid(
        robot_id,
        body_boot=7,
        origin_id="odom-1",
        anchor_id="tag-4",
        calibration_id="cal-5",
        camera_boot=21,
        width=2,
        height=1,
        envelope=envelope,
        anchored=True,
        map_to_odom=PlanarTransform("map", "odom", 0, 0, 0),
    )
    now = 1_000_000
    for lane, kind, cells in (
        (0, "floor_unsafe", (EDGE,)),
        (1, "floor_supported", (CUP,)),
        (4, "obstacle_clear", (EDGE,)),
        (5, "obstacle_hit", (CUP,)),
    ):
        runtime.record_range_batch(
            robot_id,
            RangeCellBatch(
                robot_id, 7, "odom-1", grid.epoch, "cal-5",
                lane, 1, 100_000, now, kind, cells, True,
            ),
            now_us=now,
        )
    assert grid.snapshot(now_us=now).support == ("unsafe", "occupied")

    runtime.invalidate_robot(robot_id, reason="pickup")
    unanchored = runtime.state(robot_id).grid.snapshot(now_us=now + 10_000)
    assert not unanchored.anchored
    assert unanchored.support == ("unknown", "unknown")

    reanchored = runtime.bind_qualified_grid(
        robot_id,
        body_boot=8,
        origin_id="odom-2",
        anchor_id="tag-4",
        calibration_id="cal-5",
        camera_boot=21,
        width=2,
        height=1,
        envelope=envelope,
        anchored=True,
        map_to_odom=PlanarTransform("map", "odom", 20, 0, 0),
    )
    later = now + 5_000_000
    snap = reanchored.snapshot(now_us=later)
    assert snap.anchored
    assert snap.support == ("unsafe", "unknown")
    assert reanchored.log_odds(*CUP) == 0.0
