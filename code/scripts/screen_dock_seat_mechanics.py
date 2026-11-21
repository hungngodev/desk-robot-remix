"""Paper-only 2D placement screen for TWO independent NC dock-seat switches.

Use measured switch body, actuation and optical geometry with the actual
OpenSCAD passive dock source. It neither drills final holes, enables charging
nor verifies physical collision, electrical polarity or motor stopping.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CAD = ROOT / "docs/cad/remixes/dock/dock_passive_fit.scad"
NUMERICS = (
    "seat_pair_spacing_mm", "switch_body_width_mm", "switch_body_height_mm",
    "switch_center_z_mm", "ir_emitter_center_z_mm",
    "operating_displacement_mm", "planned_stop_displacement_mm",
    "safe_total_displacement_mm",
)


def dock_constants(source: Path = CAD) -> dict:
    text = source.read_text(encoding="utf-8")
    names = (
        "track_outer_width_mm", "side_clearance_each_mm",
        "guide_wall_mm", "wall_outside_margin_mm",
        "backstop_height_mm", "base_thickness_mm", "tag_black_side_mm",
        "tag_white_margin_each_mm", "tag_paper_slack_each_mm",
        "tag_bottom_z_mm", "ir_pair_spacing_mm", "ir_probe_bore_d_mm",
    )
    values = {}
    for name in names:
        matches = re.findall(
            rf"^{name}\s*=\s*(\d+(?:\.\d+)?)\s*;", text, re.M
        )
        if len(matches) != 1:
            raise ValueError("Missing or ambiguous dock CAD datum: " + name)
        values[name] = float(matches[0])
    if not all(math.isfinite(v) and 0 < v < 1000 for v in values.values()):
        raise ValueError("Invalid dock CAD dimensions")
    width = (
        values["track_outer_width_mm"]
        + 2 * values["side_clearance_each_mm"]
        + 2 * (values["guide_wall_mm"] + values["wall_outside_margin_mm"])
    )
    paper = (
        values["tag_black_side_mm"]
        + 2 * (values["tag_white_margin_each_mm"]
               + values["tag_paper_slack_each_mm"])
    )
    if not 0 < paper < width or not 0 < values["ir_pair_spacing_mm"] < width:
        raise ValueError("Dock tag/IR source geometry is inconsistent")
    return {
        "backstop_width_mm": width,
        "backstop_min_z_mm": values["base_thickness_mm"],
        "backstop_max_z_mm": (
            values["base_thickness_mm"] + values["backstop_height_mm"]
        ),
        "tag_paper_x_min_mm": (width - paper) / 2,
        "tag_paper_x_max_mm": (width + paper) / 2,
        "tag_paper_z_min_mm": values["tag_bottom_z_mm"],
        "tag_paper_z_max_mm": values["tag_bottom_z_mm"] + paper,
        "ir_pair_spacing_mm": values["ir_pair_spacing_mm"],
        "ir_hole_radius_mm": values["ir_probe_bore_d_mm"] / 2,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }


def _numeric(value: object) -> bool:
    # A huge Python int overflows math.isfinite. Bound before conversion.
    return (
        type(value) in (int, float) and 0 < value <= 500
        and math.isfinite(value)
    )


def screen(measurements: dict, *, cad: Path = CAD) -> dict:
    if not isinstance(measurements, dict):
        raise ValueError("Exact measured dock-seat input object required")
    if set(measurements) != {"dock_id", "cad_source_sha256", *NUMERICS}:
        raise ValueError("Dock-seat record has missing or unexpected fields")
    if type(measurements["dock_id"]) is not int or not (
        1 <= measurements["dock_id"] <= 5
    ):
        raise ValueError("Physical dock ID 1 through 5 required")
    if any(not _numeric(measurements[k]) for k in NUMERICS):
        raise ValueError("Every dock-seat dimension needs finite measured mm")
    geometry = dock_constants(cad)
    if measurements["cad_source_sha256"] != geometry["source_sha256"]:
        raise ValueError("Stale dock CAD source revision for seat measurement")
    width = geometry["backstop_width_mm"]
    d = measurements
    margin = 2.0
    cx_left = (width - d["seat_pair_spacing_mm"]) / 2
    cx_right = (width + d["seat_pair_spacing_mm"]) / 2
    switch_centers = [cx_left, cx_right]
    ir_centers = [
        (width - geometry["ir_pair_spacing_mm"]) / 2,
        (width + geometry["ir_pair_spacing_mm"]) / 2,
    ]
    paper = (
        geometry["tag_paper_x_min_mm"],
        geometry["tag_paper_x_max_mm"],
        geometry["tag_paper_z_min_mm"],
        geometry["tag_paper_z_max_mm"],
    )
    checks = []
    for side, center_x, emitter_x in zip(
        ("left", "right"), switch_centers, ir_centers, strict=True
    ):
        x0 = center_x - d["switch_body_width_mm"] / 2
        x1 = center_x + d["switch_body_width_mm"] / 2
        z0 = d["switch_center_z_mm"] - d["switch_body_height_mm"] / 2
        z1 = d["switch_center_z_mm"] + d["switch_body_height_mm"] / 2
        body_inside = (
            x0 >= margin and x1 <= width - margin
            and z0 >= geometry["backstop_min_z_mm"] + margin
            and z1 <= geometry["backstop_max_z_mm"] - margin
        )
        tag_clear = (
            x1 + margin <= paper[0] or x0 - margin >= paper[1]
            or z1 + margin <= paper[2] or z0 - margin >= paper[3]
        )
        # Minimum 2D distance from emitter hole center to rectangular
        # switch envelope. It is NOT a 3D mount or wire bend verification.
        dx = max(x0 - emitter_x, emitter_x - x1, 0)
        dz = max(z0 - d["ir_emitter_center_z_mm"],
                 d["ir_emitter_center_z_mm"] - z1, 0)
        ir_clear = math.hypot(dx, dz) >= (
            geometry["ir_hole_radius_mm"] + margin
        )
        checks.append({
            "side": side, "source_body_x_mm": [x0, x1],
            "source_body_z_mm": [z0, z1],
            "within_backstop_with_2mm_web": body_inside,
            "avoids_apriltag_paper_with_2mm_gap": tag_clear,
            "avoids_nominal_ir_hole_with_2mm_gap": ir_clear,
        })
    independent_separation = (
        d["seat_pair_spacing_mm"] - d["switch_body_width_mm"] >= 2 * margin
    )
    actuation = (
        d["operating_displacement_mm"]
        < d["planned_stop_displacement_mm"]
        <= d["safe_total_displacement_mm"]
    )
    fits = (
        all(c["within_backstop_with_2mm_web"]
            and c["avoids_apriltag_paper_with_2mm_gap"]
            and c["avoids_nominal_ir_hole_with_2mm_gap"]
            for c in checks)
        and independent_separation and actuation
    )
    return {
        "dock_id": d["dock_id"],
        "cad_source_sha256": geometry["source_sha256"],
        "source_only_layout_possible": fits,
        "switch_pair_separately_located": independent_separation,
        "stop_displacement_inside_measured_travel": actuation,
        "switches": checks,
        "normally_closed_polarity_physically_tested": False,
        "switch_bounce_and_faults_physically_tested": False,
        "actual_carrier_depth_and_wire_clearance_tested": False,
        "physical_dock_seating_qualified": False,
        "charging_authorized": False,
    }


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate dock-seat measurement field")
        result[key] = value
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--measurements", type=Path, required=True)
    args = parser.parse_args()
    values = json.loads(
        args.measurements.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicates,
        parse_constant=lambda _value: (_ for _ in ()).throw(
            ValueError("Nonfinite dock-seat measurement")
        ),
    )
    print(json.dumps(screen(values), indent=2))


if __name__ == "__main__":
    main()
