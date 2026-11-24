from dataclasses import replace

import pytest
from desk_robot.spatial_grid import RangeCellBatch, SpatialGrid


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
