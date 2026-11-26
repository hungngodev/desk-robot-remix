"""Synthetic sweep rejection checks; no installed geometry is qualified."""
import runpy
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "docs/cad/remixes/mg90s_sweep_screen.py"
MODULE = runpy.run_path(str(SOURCE))
sweep_bounds = MODULE["sweep_bounds"]
overlapping_keepouts = MODULE["overlapping_keepouts"]


def keepouts():
    return {name: ((100, 100, 100), (101, 101, 101))
            for name in MODULE["REQUIRED_KEEPOUTS"]}


def test_continuous_arc_catches_interior_extremum_and_endpoints():
    sweep = sweep_bounds((0, 0), 10, 60, 120, (2, 4), 0.5)
    boxes = keepouts()
    boxes["tof_0"] = ((-0.1, 10.1, 2), (0.1, 10.3, 3))
    boxes["battery_cover"] = ((5.1, 8.5, 2), (5.3, 9, 3))
    boxes["tof_7"] = ((-5.3, 8.5, 2), (-5.1, 9, 3))
    boxes["tof_1"] = ((-0.1, 10.1, 4.6), (0.1, 10.3, 5))
    assert overlapping_keepouts(sweep, boxes) == ("battery_cover", "tof_0", "tof_7")


def test_contact_and_missing_keepout_fail_closed():
    sweep = sweep_bounds((0, 0), 10, 0, 90, (2, 4), 0.5)
    boxes = keepouts()
    assert overlapping_keepouts(sweep, boxes) == ()
    boxes["battery_cover"] = ((10.5, 0, 2), (11, 1, 3))
    assert overlapping_keepouts(sweep, boxes) == ("battery_cover",)
    del boxes["tof_7"]
    with pytest.raises(ValueError, match="eight ToF"):
        overlapping_keepouts(sweep, boxes)


@pytest.mark.parametrize("angles, margin", [((120, 60), 0.5), ((0, 90), 0),
                                            ((0, float("nan")), 0.5)])
def test_invalid_geometry_rejected(angles, margin):
    with pytest.raises(ValueError):
        sweep_bounds((0, 0), 10, *angles, (2, 4), margin)
