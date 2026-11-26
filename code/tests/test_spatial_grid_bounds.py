"""Desk-scale grid capacity and atomic coordinate rejection regressions."""

from dataclasses import replace

import pytest
from desk_robot.spatial_grid import CELL_MM, GridEvidenceError, RangeCellBatch, SpatialGrid


FAR_CELL = 10**12 // CELL_MM  # One billion metres, converted to cell units.


def grid(width=64, height=64):
    return SpatialGrid("robot-01", 7, "odom-1", "tag-4", "cal-1", width, height)


def evidence(cells, sequence=1):
    return RangeCellBatch(
        "robot-01", 7, "odom-1", 0, "cal-1", 4, sequence,
        100_000 + sequence, 1_000_000 + sequence, "obstacle_hit", cells, True,
    )


@pytest.mark.parametrize("size", [0, 65, 10_000 // CELL_MM + 1, FAR_CELL, -FAR_CELL])
@pytest.mark.parametrize("axis", [0, 1])
def test_grid_dimensions_reject_impossible_desk_extent(size, axis):
    dimensions = [64, 64]
    dimensions[axis] = size
    with pytest.raises(ValueError, match="bounded spatial grid"):
        grid(*dimensions)


@pytest.mark.parametrize("point", [
    (FAR_CELL, 0), (-FAR_CELL, 0), (0, FAR_CELL), (0, -FAR_CELL),
    (501, 0), (0, 501), (64, 0), (0, 64), (-1, 0), (0, -1),
    (True, 0), (0, 1.0), ([], 0),
])
def test_invalid_coordinates_cannot_write_or_read_evidence(point):
    g = grid()
    first = evidence(((0, 0),))
    g.record(first, now_us=first.received_us)
    candidate = evidence(((1, 1), point), sequence=2)
    before = g.snapshot(now_us=candidate.received_us)
    with pytest.raises(GridEvidenceError):
        g.record(candidate, now_us=candidate.received_us)
    assert g.snapshot(now_us=candidate.received_us) == before
    assert len(g._cells) == 1
    with pytest.raises(ValueError):
        g.state(*point, now_us=candidate.received_us)
    with pytest.raises(ValueError):
        g.log_odds(*point)
    # The rejected batch must not consume the source sequence.
    valid = replace(candidate, cells=((1, 1),))
    g.record(valid, now_us=valid.received_us)
    assert g.log_odds(1, 1) == pytest.approx(1.2)
    assert len(g._cells) == 2


def test_full_grid_stays_bounded_under_repeated_observations():
    g = grid()
    cells = tuple((x, y) for y in range(64) for x in range(64))
    for sequence, start in enumerate(range(0, len(cells), 256), 1):
        batch = evidence(cells[start:start + 256], sequence)
        g.record(batch, now_us=batch.received_us)
    assert len(g._cells) == 4096
    assert len(g.snapshot(now_us=batch.received_us).support) == 4096
    repeat = evidence(cells[:256], sequence + 1)
    g.record(repeat, now_us=repeat.received_us)
    assert len(g._cells) == 4096
    assert g.log_odds(63, 63) == pytest.approx(1.2)
