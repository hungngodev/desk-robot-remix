from dataclasses import replace

import pytest
from desk_robot.spatial_grid import GridEvidenceError, RangeCellBatch, SpatialGrid


def test_returning_to_calibration_cannot_restore_old_evidence():
    grid = SpatialGrid('robot-01', 7, 'odom-1', 'tag-4', 'camera-a', 4, 3)
    floor = RangeCellBatch('robot-01', 7, 'odom-1', 0, 'camera-a', 0, 1,
                           100_000, 1_000_000, 'floor_supported', ((1, 1),), True)
    clear = replace(floor, lane=4, kind='obstacle_clear')
    grid.record(floor, now_us=1_000_000)
    grid.record(clear, now_us=1_000_000)
    assert grid.state(1, 1, now_us=1_000_001) == 'safe'
    grid.invalidate_calibration('camera-b')
    grid.invalidate_calibration('camera-a')
    assert grid.state(1, 1, now_us=1_000_002) == 'out_of_calibration'
    assert grid.snapshot(now_us=1_000_002).support[5] == 'unsafe'
    floor = replace(floor, epoch=2, sequence=2, sample_us=200_000,
                    received_us=1_100_000)
    grid.record(floor, now_us=1_100_000)
    assert grid.state(1, 1, now_us=1_100_000) == 'out_of_calibration'
    hit = replace(floor, lane=4, kind='obstacle_hit')
    grid.record(hit, now_us=1_100_000)
    assert grid.log_odds(1, 1) == pytest.approx(1.2)
    assert grid.state(1, 1, now_us=1_100_000) == 'occupied'


def test_calibration_and_same_boot_origin_transitions_preserve_clock_offset(tmp_path):
    from pathlib import Path

    from desk_robot.config import load_settings
    from desk_robot.memory import MemoryStore
    from desk_robot.route_planner import SafetyEnvelope
    from desk_robot.spatial_runtime import SpatialRuntime

    for mode in ("calibration", "same_boot_origin"):
        grid = SpatialGrid('r', 7, 'o', 'a', 'c', 3, 3)
        floor = RangeCellBatch('r', 7, 'o', 0, 'c', 0, 1,
                               1_000_000, 2_000_000, 'floor_supported', ((1, 1),), True)
        clear = replace(floor, lane=4, kind='obstacle_clear')
        grid.record(floor, now_us=2_000_000)
        grid.record(clear, now_us=2_000_000)
        assert grid.state(1, 1, now_us=2_000_000) == 'safe'

        if mode == "calibration":
            grid.invalidate_calibration('c-new')
            next_origin, next_cal = 'o', 'c-new'
        else:
            grid.invalidate_origin(7, 'new-origin')
            next_origin, next_cal = 'new-origin', 'c'

        lagged_floor = RangeCellBatch(
            'r', 7, next_origin, 1, next_cal, 0, 2,
            1_100_000, 2_500_000, 'floor_supported', ((1, 1),), True,
        )
        with pytest.raises(GridEvidenceError, match="source clock diverged"):
            grid.record(lagged_floor, now_us=2_500_000)
        assert grid.state(1, 1, now_us=2_500_000) != 'safe'

    # True WROOM reboot changes body_boot and resets the clock baseline cleanly.
    reboot_grid = SpatialGrid('r', 7, 'o', 'a', 'c', 3, 3)
    reboot_grid.record(
        RangeCellBatch('r', 7, 'o', 0, 'c', 0, 1,
                       1_000_000, 2_000_000, 'floor_supported', ((1, 1),), True),
        now_us=2_000_000,
    )
    reboot_grid.invalidate_origin(8, 'reboot-origin')
    reboot_grid.record(
        RangeCellBatch('r', 8, 'reboot-origin', 1, 'c', 0, 1,
                       1_100_000, 2_500_000, 'floor_supported', ((1, 1),), True),
        now_us=2_500_000,
    )
    assert reboot_grid.state(1, 1, now_us=2_500_000) == 'unknown'

    # Replacing the SpatialGrid in SpatialRuntime for unchanged body_boot retains offset.
    settings = load_settings(
        Path(__file__).resolve().parents[1] / "config/fleet.simulation.toml"
    )
    memory = MemoryStore(tmp_path, [r.id for r in settings.robots])
    runtime = SpatialRuntime(settings, memory)
    env = SafetyEnvelope(3, 2, 2, 15, True)
    runtime.bind_qualified_grid(
        "robot-01", body_boot=7, origin_id="o1", anchor_id="a1",
        calibration_id="c1", camera_boot=10, width=3, height=3, envelope=env,
        anchored=True,
    )
    epoch1 = runtime.state("robot-01").epoch
    runtime.record_range_batch(
        "robot-01",
        RangeCellBatch("robot-01", 7, "o1", epoch1, "c1", 0, 1,
                       1_000_000, 2_000_000, "floor_supported", ((1, 1),), True),
        now_us=2_000_000,
    )
    runtime.bind_qualified_grid(
        "robot-01", body_boot=7, origin_id="o2", anchor_id="a1",
        calibration_id="c2", camera_boot=10, width=3, height=3, envelope=env,
        anchored=True,
    )
    epoch2 = runtime.state("robot-01").epoch
    with pytest.raises(GridEvidenceError, match="source clock diverged"):
        runtime.record_range_batch(
            "robot-01",
            RangeCellBatch("robot-01", 7, "o2", epoch2, "c2", 0, 1,
                           1_100_000, 2_500_000, "floor_supported", ((1, 1),), True),
            now_us=2_500_000,
        )
