"""Metric grid indexing must not turn an off-desk point into cell zero."""

import math

import pytest
from desk_robot.spatial_grid import CELL_MM, SpatialGrid


def grid():
    return SpatialGrid("robot-01", 7, "odom-1", "tag-4", "cal-1", 4, 3)


@pytest.mark.parametrize("axis", [0, 1])
@pytest.mark.parametrize("coordinate", [-20, -1, -0.001, math.nextafter(0.0, -1.0)])
def test_negative_metric_coordinates_never_alias_cell_zero(axis, coordinate):
    point = [0.0, 0.0]
    point[axis] = coordinate
    with pytest.raises(ValueError, match="outside map"):
        grid().cell_at_mm(*point)


@pytest.mark.parametrize("axis,extent", [(0, 80), (1, 60)])
def test_metric_cells_have_half_open_bounds(axis, extent):
    g = grid()
    assert g.snapshot(now_us=0).cell_mm == CELL_MM == 20
    point = [0.0, 0.0]
    for boundary in range(20, extent, 20):
        point[axis] = math.nextafter(boundary, 0.0)
        assert g.cell_at_mm(*point)[axis] == boundary // 20 - 1
        point[axis] = boundary
        assert g.cell_at_mm(*point)[axis] == boundary // 20
    point[axis] = math.nextafter(extent, 0.0)
    assert g.cell_at_mm(*point)[axis] == extent // 20 - 1
    for coordinate in (extent, math.nextafter(extent, math.inf), 10**1000):
        point[axis] = coordinate
        with pytest.raises(ValueError, match="outside map"):
            g.cell_at_mm(*point)


@pytest.mark.parametrize("coordinate", [math.nan, math.inf, -math.inf, True, "20"])
@pytest.mark.parametrize("axis", [0, 1])
def test_non_metric_coordinates_are_rejected(axis, coordinate):
    point = [0, 0]
    point[axis] = coordinate
    with pytest.raises(ValueError, match="outside map"):
        grid().cell_at_mm(*point)


def test_rectangular_grid_metric_lookup_preserves_xy_order():
    g = grid()
    assert g.cell_at_mm(79.5, 59.5) == (3, 2)
    assert g.cell_at_mm(20, 40) == (1, 2)
    assert g.cell_at_mm(0, -0.0) == (0, 0)
    assert g.state(*g.cell_at_mm(79.5, 59.5), now_us=0) == "unknown"
    assert g.log_odds(*g.cell_at_mm(79.5, 59.5)) == 0.0
