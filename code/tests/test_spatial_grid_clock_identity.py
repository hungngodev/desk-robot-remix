from dataclasses import replace

import pytest

from desk_robot.spatial_grid import GridEvidenceError, RangeCellBatch, SpatialGrid


def test_first_forward_lane_cannot_hide_old_conversion():
    grid = SpatialGrid('r', 1, 'o', 'a', 'c', 3, 3)
    floor = RangeCellBatch('r', 1, 'o', 0, 'c', 0, 1, 1_000_000, 2_000_000,
                           'floor_supported', ((1, 1),), True)
    grid.record(floor, now_us=2_000_000)
    grid.anchored = True
    old = replace(floor, lane=4, kind='obstacle_clear', sample_us=100_000)
    with pytest.raises(GridEvidenceError, match='clock diverged'):
        grid.record(old, now_us=2_000_000)
    assert not grid.anchored
    assert grid.state(1, 1, now_us=2_000_000) != 'safe'


@pytest.mark.parametrize('fields', [{'body_boot': True}, {'epoch': False}])
def test_boolean_identity_not_accepted(fields):
    grid = SpatialGrid('r', 1, 'o', 'a', 'c', 3, 3)
    floor = RangeCellBatch('r', 1, 'o', 0, 'c', 0, 1, 1_000_000, 2_000_000,
                           'floor_supported', ((1, 1),), True)
    with pytest.raises(GridEvidenceError):
        grid.record(replace(floor, **fields), now_us=2_000_000)
    assert grid.state(1, 1, now_us=2_000_000) == 'unknown'


def test_later_lane_reveals_old_initial_floor_sample():
    grid = SpatialGrid('r', 1, 'o', 'a', 'c', 3, 3)
    floor = RangeCellBatch('r', 1, 'o', 0, 'c', 0, 1, 100_000, 2_000_000,
                           'floor_supported', ((1, 1),), True)
    grid.record(floor, now_us=2_000_000)
    clear = replace(floor, lane=4, kind='obstacle_clear', sample_us=1_000_000)
    grid.record(clear, now_us=2_000_000)
    assert grid.state(1, 1, now_us=2_000_000) == 'stale'
    fresh = replace(floor, sequence=2, sample_us=1_010_000, received_us=2_010_000)
    grid.record(fresh, now_us=2_010_000)
    assert grid.state(1, 1, now_us=2_010_000) == 'safe'
