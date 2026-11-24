import pytest
from desk_robot.spatial_grid import GridEvidenceError, RangeCellBatch, SpatialGrid


def grid():
    return SpatialGrid('robot-01', 7, 'odom-1', 'tag-4', 'camera-abc', 4, 3)


def evidence(kind, lane, sample_us, received_us, cells=((1, 1),)):
    return RangeCellBatch('robot-01', 7, 'odom-1', 0, 'camera-abc', lane, 1,
                          sample_us, received_us, kind, cells, True)


@pytest.mark.parametrize('kind, hazard, lane, hazard_lane, expected', [
    ('floor_supported', 'floor_unsafe', 0, 1, 'unsafe'),
    ('obstacle_clear', 'obstacle_hit', 4, 5, 'occupied'),
])
@pytest.mark.parametrize('sample_us, received_us', [
    (100_000, 1_100_000),  # stale capture, later receipt
    (200_000, 1_050_000),  # tied capture, earlier receipt
    (200_000, 1_100_000),  # tied capture, later receipt
])
def test_cross_lane_delayed_clearance_cannot_replace_hazard(
    kind, hazard, lane, hazard_lane, expected, sample_us, received_us,
):
    g = grid()
    if kind == 'floor_supported':
        g.record(evidence('obstacle_clear', 4, 100_000, 1_000_000), now_us=1_000_000)
    else:
        g.record(evidence('floor_supported', 0, 100_000, 1_000_000), now_us=1_000_000)
    g.record(evidence(hazard, hazard_lane, 200_000, 1_060_000), now_us=1_060_000)
    with pytest.raises(GridEvidenceError, match='cell evidence'):
        g.record(evidence(kind, lane, sample_us, received_us, ((2, 1), (1, 1))),
                 now_us=1_100_000)
    assert g.state(1, 1, now_us=1_100_000) == expected
    assert (2, 1) not in g._cells
    assert g.snapshot(now_us=1_100_000).observed_at_us == 1_060_000


def test_later_floor_support_can_requalify_cell():
    g = grid()
    g.record(evidence('obstacle_clear', 4, 100_000, 1_000_000), now_us=1_000_000)
    g.record(evidence('floor_unsafe', 1, 200_000, 1_060_000), now_us=1_060_000)
    g.record(evidence('floor_supported', 0, 300_000, 1_100_000), now_us=1_100_000)
    assert g.state(1, 1, now_us=1_100_000) == 'safe'
