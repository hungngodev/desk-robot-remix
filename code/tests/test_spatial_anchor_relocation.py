"""Synthetic map correction must retire old occupancy, not invent free space."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from desk_robot.memory import MemoryStore
from desk_robot.route_planner import SafetyEnvelope
from desk_robot.spatial_frames import PlanarTransform
from desk_robot.spatial_grid import CELL_MM, GridEvidenceError, RangeCellBatch
from desk_robot.spatial_runtime import SpatialRuntime


@pytest.mark.parametrize("anchor_id", ["tag-1", "tag-2"])
def test_anchor_correction_retires_ghost_wall(tmp_path, anchor_id):
    robot_id = "robot-01"
    settings = SimpleNamespace(robots=[SimpleNamespace(id=robot_id)])
    runtime = SpatialRuntime(settings, MemoryStore(tmp_path, [robot_id]))
    binding = dict(
        body_boot=7, origin_id="11", calibration_id="cal-1", camera_boot=21,
        width=6, height=6, envelope=SafetyEnvelope(3, 2, 2, 15, True),
        anchored=True,
    )
    before = runtime.bind_qualified_grid(
        robot_id, anchor_id="tag-1", map_to_odom=PlanarTransform("map", "odom", 0, 0, 0),
        **binding,
    )
    wall = (2, 2)
    hit = RangeCellBatch(
        robot_id, 7, "11", before.epoch, "cal-1", 4, 1,
        100_000, 1_000_000, "obstacle_hit", (wall,), True,
    )
    floor = replace(hit, lane=0, kind="floor_supported")
    runtime.record_range_batch(robot_id, floor, now_us=1_000_000)
    runtime.record_range_batch(robot_id, hit, now_us=1_000_000)
    assert before.state(*wall, now_us=1_000_000) == "occupied"
    assert before.log_odds(*wall) == pytest.approx(1.2)

    # One-cell map-to-odom correction, with the same body/head/calibration.
    # Even reuse of the same tag ID must create a distinct map epoch.
    corrected = runtime.bind_qualified_grid(
        robot_id, anchor_id=anchor_id,
        map_to_odom=PlanarTransform("map", "odom", CELL_MM, 0, 0), **binding,
    )
    assert corrected is not before
    assert corrected.epoch == before.epoch + 1
    assert corrected.state(*wall, now_us=1_100_000) == "unknown"
    assert corrected.log_odds(*wall) == 0.0
    with pytest.raises(GridEvidenceError):
        runtime.record_range_batch(robot_id, hit, now_us=1_100_000)

    new_wall = (wall[0] + 1, wall[1])
    fresh = replace(
        hit, epoch=corrected.epoch, sequence=2, sample_us=200_000,
        received_us=1_100_000, cells=(new_wall,),
    )
    runtime.record_range_batch(
        robot_id, replace(fresh, lane=0, kind="floor_supported"), now_us=1_100_000,
    )
    runtime.record_range_batch(robot_id, fresh, now_us=1_100_000)
    snapshot = corrected.snapshot(now_us=1_100_000)
    assert snapshot.anchored and snapshot.anchor_id == anchor_id
    assert snapshot.support.count("occupied") == 1
    assert snapshot.support[wall[1] * snapshot.width + wall[0]] == "unknown"
    assert snapshot.support[new_wall[1] * snapshot.width + new_wall[0]] == "occupied"
