"""The battery tray mounting holes must not break through the tab edges."""
from pathlib import Path
import re

CAD = Path(__file__).resolve().parents[2] / "docs/cad/remixes/remaining_fit_gauges.scad"


def test_battery_tray_mounting_bores_are_enclosed_by_both_tabs():
    source = CAD.read_text(encoding="utf-8")
    diameter = float(re.search(r"^m3_clearance = ([0-9.]+);", source, re.M).group(1))
    radius = diameter / 2
    # Both tabs extend 8 mm along X and 9 mm along Y. A bore centered
    # on a tab edge cuts an open notch rather than a retained screw hole.
    left = re.search(
        r"translate\(\[-4,([0-9.]+),base/2\]\) cylinder\(h=base\+1,d=m3_clearance,center=true\);",
        source,
    )
    right = re.search(
        r"translate\(\[l\+4,w-([0-9.]+),base/2\]\) cylinder\(h=base\+1,d=m3_clearance,center=true\);",
        source,
    )
    assert left is not None and right is not None
    left_y = float(left.group(1))
    right_y_offset = float(right.group(1))
    assert 9.5 + radius <= left_y <= 18.5 - radius
    assert 5 + radius <= right_y_offset <= 14 - radius
    assert radius < 4
