"""Synthetic sweep rejection checks; no installed geometry is qualified."""
import json
import runpy
import subprocess
import sys
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


def assembly_record():
    # Synthetic geometry, not a measured robot or an aligned Fusion export.
    return {
        "assembly_revision": "synthetic-fixture",
        **{
            servo: {
                "pivot_mm": [0, 0], "reach_mm": 10,
                "start_deg": 0, "end_deg": 90, "z_span_mm": [2, 4],
                "margin_mm": 0.5, "keepouts_mm": keepouts(),
            }
            for servo in ("lift", "jaw")
        },
    }


def test_assembly_record_cli_reports_both_servos_and_keeps_hold(tmp_path):
    record = assembly_record()
    path = tmp_path / "synthetic.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    clear = subprocess.run([sys.executable, str(SOURCE), str(path)],
                           capture_output=True, text=True, check=True)
    receipt = json.loads(clear.stdout)
    assert receipt["physical_qualification"] == "HOLD"
    assert receipt["input_provenance"] == "operator_supplied_unverified"
    assert receipt["screen_scope"] == "standalone_aabb_rejection_only"
    assert receipt["assembly_revision"] == "synthetic-fixture"
    assert set(receipt["servos"]) == {"lift", "jaw"}
    assert all(not servo["potential_overlaps"] for servo in receipt["servos"].values())
    record["jaw"]["keepouts_mm"]["tof_7"] = [[0, 0, 2], [1, 1, 3]]
    path.write_text(json.dumps(record), encoding="utf-8")
    blocked = subprocess.run([sys.executable, str(SOURCE), str(path)],
                             capture_output=True, text=True, check=False)
    assert blocked.returncode == 1
    receipt = json.loads(blocked.stdout)
    assert receipt["servos"]["lift"]["potential_overlaps"] == []
    assert receipt["servos"]["jaw"]["potential_overlaps"] == ["tof_7"]
    assert receipt["physical_qualification"] == "HOLD"


@pytest.mark.parametrize("missing", ["lift", "jaw", "assembly_revision", "tof_7"])
def test_incomplete_assembly_record_never_returns_clear_receipt(tmp_path, missing):
    record = assembly_record()
    if missing == "tof_7":
        del record["jaw"]["keepouts_mm"][missing]
    else:
        del record[missing]
    path = tmp_path / "incomplete.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    result = subprocess.run([sys.executable, str(SOURCE), str(path)],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 2
    assert not result.stdout
    assert "HOLD" in result.stderr
