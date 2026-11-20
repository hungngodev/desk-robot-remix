"""Source-level invariants for the unpowered passive docking fit coupon.

These checks do not qualify printed dimensions or powered charging.
"""
import re
from pathlib import Path

SOURCE = (
    Path(__file__).resolve().parents[2]
    / "docs/cad/remixes/dock/dock_passive_fit.scad"
)


def test_dock_rail_preserves_selected_straight_channel_and_entry_flare():
    source = SOURCE.read_text()
    def value(name):
        match = re.search(r"^" + re.escape(name) + r"\s*=\s*([0-9.]+)\s*;", source, re.M)
        assert match is not None, name
        return float(match.group(1))

    track = value("track_outer_width_mm")
    clearance = value("side_clearance_each_mm")
    wall = value("guide_wall_mm")
    margin = value("wall_outside_margin_mm")
    flare = value("entry_flare_each_mm")
    assert wall > 0 and margin >= flare
    channel = track + 2 * clearance
    inner_x = wall + margin
    outside = channel + 2 * inner_x
    # Geometric clearance is between opposing rail INNER faces.
    assert abs((outside - 2 * inner_x) - channel) < 1e-6
    # At y=0 both rail faces shift OUTWARD equally, preserving wall thickness.
    assert "[inner_wall_x - guide_wall_mm - entry_flare_each_mm, 0]" in source
    assert "[inner_wall_x - entry_flare_each_mm, 0]" in source
    assert "[inner_wall_x, 37]" in source
    assert "[inner_wall_x - guide_wall_mm, 37]" in source
    assert (outside - 2 * (inner_x - flare)) > channel
    assert "intersection()" in source
    assert "dock_rail_entry_coupon()" in source


def test_dock_geometry_remains_explicitly_passive():
    source = SOURCE.read_text()
    assert "never an energized charging cradle" in source
    assert "Nominal dimensions are an example, not measured robot fit" in source
    assert "no AprilTag, stop or charging contacts" in source
