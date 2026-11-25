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
CONTACT_CAD = ROOT / "docs/cad/remixes/remaining_fit_gauges.scad"
PER_SWITCH_NUMERICS = (
    "switch_body_width_mm", "switch_body_height_mm", "switch_center_z_mm",
    "ir_emitter_center_z_mm", "operating_displacement_mm",
    "planned_stop_displacement_mm", "safe_total_displacement_mm",
    "required_travel_reserve_mm",
)
NUMERICS = ("seat_pair_spacing_mm",) + tuple(
    f"{side}_{name}" for side in ("left", "right")
    for name in PER_SWITCH_NUMERICS
) + (
    "contact_center_y_mm", "robot_underside_z_at_stop_mm",
    "required_contact_top_gap_mm",
)


def dock_constants(source: Path = CAD) -> dict:
    text = source.read_text(encoding="utf-8")
    names = (
        "track_outer_width_mm", "side_clearance_each_mm",
        "guide_wall_mm", "wall_outside_margin_mm",
        "guide_run_mm", "guide_height_mm", "entry_flare_each_mm",
        "entry_coupon_length_mm",
        "base_length_mm", "backstop_thickness_mm",
        "backstop_height_mm", "backstop_brace_depth_mm",
        "backstop_brace_height_mm", "base_thickness_mm", "tag_black_side_mm",
        "tag_white_margin_each_mm", "tag_paper_slack_each_mm",
        "tag_recess_depth_mm",
        "tag_bottom_z_mm", "ir_pair_spacing_mm", "ir_probe_bore_d_mm",
        "ir_min_tag_web_mm", "ir_coupon_height_mm", "ir_coupon_thickness_mm",
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
    # Keep this paper screen aligned with the printable geometry's assert
    # contract. It must not greenlight a switch layout on an SCAD file
    # whose rails, entry coupon, tag pocket or IR coupon cannot render.
    inner_wall = values["guide_wall_mm"] + values["wall_outside_margin_mm"]
    if (not 40 < values["track_outer_width_mm"] < 200
            or not 0.5 <= values["side_clearance_each_mm"] < 8
            or min(values["guide_height_mm"], values["guide_wall_mm"],
                   values["base_thickness_mm"]) < 2
            or not values["guide_run_mm"] > 37
            or not 37 < values["entry_coupon_length_mm"] < values["guide_run_mm"]
            or not values["base_length_mm"] >
                values["guide_run_mm"] + values["backstop_thickness_mm"]
            or not values["base_length_mm"] - values["backstop_thickness_mm"]
                - values["backstop_brace_depth_mm"] > values["guide_run_mm"]
            or not values["backstop_brace_height_mm"] <= values["backstop_height_mm"]
            or not 0 < values["entry_flare_each_mm"] <=
                values["wall_outside_margin_mm"]
            or not values["entry_flare_each_mm"] < inner_wall
            or not 10 <= values["tag_black_side_mm"] <= 75
            or not 4 <= values["tag_white_margin_each_mm"] <= 10
            or not 0.25 <= values["tag_paper_slack_each_mm"] <= 1.5
            or not 0.4 <= values["tag_recess_depth_mm"] <
                values["backstop_thickness_mm"] - 2
            or not 1 < values["ir_probe_bore_d_mm"] < 15
            or not values["ir_min_tag_web_mm"] >= 3
            or not values["ir_coupon_thickness_mm"] >= 2
            or not values["ir_coupon_height_mm"] >= 10
            or not values["ir_coupon_height_mm"] / 2 -
                values["ir_probe_bore_d_mm"] / 2 >=
                values["ir_min_tag_web_mm"]):
        raise ValueError("Dock SCAD source violates printable geometry constraints")
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
    # A printed IR-position coupon must not cut the AprilTag paper's
    # white quiet zone or leave too little material at the outside edge.
    # Source SCAD enforces both radial web widths independently.
    half_spacing = values["ir_pair_spacing_mm"] / 2
    hole_radius = values["ir_probe_bore_d_mm"] / 2
    web = values["ir_min_tag_web_mm"]
    if (half_spacing - hole_radius - paper / 2 < web
            or width / 2 - half_spacing - hole_radius < web):
        raise ValueError("Dock IR aperture breaches printable tag/edge web")
    # Mirror the printable SCAD's tag pocket assertions. A pocket which
    # cannot exist inside the rail channel or backstop must not receive a
    # positive paper-only seat-switch layout screen.
    channel = values["track_outer_width_mm"] + 2 * values["side_clearance_each_mm"]
    floor = values["base_thickness_mm"]
    if (paper >= channel
            or values["tag_bottom_z_mm"] < floor + values["backstop_brace_height_mm"] + 2
            or values["tag_bottom_z_mm"] + paper + 3 >
                floor + values["backstop_height_mm"]):
        raise ValueError("Dock tag pocket exceeds printable CAD clearance")
    return {
        "backstop_width_mm": width,
        "dock_base_length_mm": values["base_length_mm"],
        "backstop_front_y_mm": (
            values["base_length_mm"] - values["backstop_thickness_mm"]
        ),
        "backstop_brace_front_y_mm": (
            values["base_length_mm"] - values["backstop_thickness_mm"]
            - values["backstop_brace_depth_mm"]
        ),
        "backstop_brace_top_z_mm": floor + values["backstop_brace_height_mm"],
        "clear_channel_x_min_mm": (
            values["guide_wall_mm"] + values["wall_outside_margin_mm"]
        ),
        "clear_channel_x_max_mm": (
            width - values["guide_wall_mm"]
            - values["wall_outside_margin_mm"]
        ),
        "dock_base_top_z_mm": values["base_thickness_mm"],
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


def contact_constants(source: Path = CONTACT_CAD) -> dict:
    """Original NONCONDUCTIVE contact fit gauge, never a selected connector."""
    text = source.read_text(encoding="utf-8")
    values = {}
    for name in (
        "contact_carrier_l", "contact_carrier_w", "contact_carrier_h",
        "contact_centers_mm", "contact_outer_d_mm",
        "contact_pocket_depth_mm", "fit_xy", "m3_clearance",
        "minimum_pocket_floor_mm", "minimum_side_wall_mm",
        "minimum_bridge_mm",
    ):
        matches = re.findall(
            rf"^\s*{name}\s*=\s*(\d+(?:\.\d+)?)\s*;",
            text, re.M,
        )
        if len(matches) != 1:
            raise ValueError("Missing or ambiguous contact CAD datum: " + name)
        values[name] = float(matches[0])
    if not all(math.isfinite(v) and 0 < v <= 500 for v in values.values()):
        raise ValueError("Invalid unpowered contact carrier dimensions")
    if not values["contact_outer_d_mm"] < values["contact_centers_mm"] < (
        values["contact_carrier_l"] - values["contact_outer_d_mm"]
    ):
        raise ValueError("Invalid contact coupon pocket separation")
    # Mirror the nonconductive SCAD coupon's own print constraints. The
    # mounting bores must leave a real insulating bridge to both pockets.
    pocket_radius = (values["contact_outer_d_mm"] + values["fit_xy"]) / 2
    bolt_radius = values["m3_clearance"] / 2
    bolt_center = values["contact_carrier_l"] / 2 - 5
    contact_center = values["contact_centers_mm"] / 2
    if (not 8 < values["contact_centers_mm"] <
            values["contact_carrier_l"] - 14
            or not 1 < values["contact_outer_d_mm"] < 10
            or not 1 < values["contact_pocket_depth_mm"] <
                values["contact_carrier_h"]
            or (values["contact_carrier_h"] -
                values["contact_pocket_depth_mm"] <
                values["minimum_pocket_floor_mm"])
            or values["contact_carrier_w"] / 2 - pocket_radius <
                values["minimum_side_wall_mm"]
            or bolt_center - contact_center <
                bolt_radius + pocket_radius + values["minimum_bridge_mm"]):
        raise ValueError("Invalid unpowered contact carrier printable web")
    return {
        "carrier_length_mm": values["contact_carrier_l"],
        "carrier_depth_mm": values["contact_carrier_w"],
        "carrier_height_mm": values["contact_carrier_h"],
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "electrical_contact_selected": False,
    }


def _numeric(value: object) -> bool:
    # A huge Python int overflows math.isfinite. Bound before conversion.
    return (
        type(value) in (int, float) and 0 < value <= 500
        and math.isfinite(value)
    )


def screen(measurements: dict, *, cad: Path = CAD,
           contact_cad: Path = CONTACT_CAD) -> dict:
    if not isinstance(measurements, dict):
        raise ValueError("Exact measured dock-seat input object required")
    if set(measurements) != {
        "dock_id", "cad_source_sha256", "contact_cad_source_sha256",
        *NUMERICS,
    }:
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
    contact = contact_constants(contact_cad)
    if measurements["contact_cad_source_sha256"] != contact["source_sha256"]:
        raise ValueError("Stale unpowered contact carrier CAD source revision")
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
        prefix = side + "_"
        x0 = center_x - d[prefix + "switch_body_width_mm"] / 2
        x1 = center_x + d[prefix + "switch_body_width_mm"] / 2
        z0 = (d[prefix + "switch_center_z_mm"]
              - d[prefix + "switch_body_height_mm"] / 2)
        z1 = (d[prefix + "switch_center_z_mm"]
              + d[prefix + "switch_body_height_mm"] / 2)
        body_inside = (
            x0 >= margin and x1 <= width - margin
            and z0 >= geometry["backstop_min_z_mm"] + margin
            and z1 <= geometry["backstop_max_z_mm"] - margin
        )
        # The brace is full width and projects ahead of the backstop.
        # Reserve its entire projected vertical envelope before fitting
        # the switch or either emitter at the backstop plane.
        brace_top = geometry["backstop_brace_top_z_mm"]
        switch_brace_clear = z0 >= brace_top + margin
        emitter_brace_clear = (
            d[prefix + "ir_emitter_center_z_mm"]
            - geometry["ir_hole_radius_mm"] >= brace_top + margin
        )
        tag_clear = (
            x1 + margin <= paper[0] or x0 - margin >= paper[1]
            or z1 + margin <= paper[2] or z0 - margin >= paper[3]
        )
        # Minimum 2D distance from emitter hole center to rectangular
        # switch envelope. It is NOT a 3D mount or wire bend verification.
        dx = max(x0 - emitter_x, emitter_x - x1, 0)
        dz = max(z0 - d[prefix + "ir_emitter_center_z_mm"],
                 d[prefix + "ir_emitter_center_z_mm"] - z1, 0)
        ir_clear = math.hypot(dx, dz) >= (
            geometry["ir_hole_radius_mm"] + margin
        )
        # Each NC switch and IR emitter must be independently measured.
        # A good left plunger cannot authorize an unmeasured right plunger.
        actuation = (
            d[prefix + "operating_displacement_mm"]
            + d[prefix + "required_travel_reserve_mm"]
            <= d[prefix + "planned_stop_displacement_mm"]
            <= d[prefix + "safe_total_displacement_mm"]
            - d[prefix + "required_travel_reserve_mm"]
        )
        emitter_inside = (
            geometry["backstop_min_z_mm"]
            + geometry["ir_hole_radius_mm"] + margin
            <= d[prefix + "ir_emitter_center_z_mm"]
            <= geometry["backstop_max_z_mm"]
            - geometry["ir_hole_radius_mm"] - margin
        )
        checks.append({
            "side": side, "source_body_x_mm": [x0, x1],
            "source_body_z_mm": [z0, z1],
            "within_backstop_with_2mm_web": body_inside,
            "avoids_apriltag_paper_with_2mm_gap": tag_clear,
            "avoids_backstop_brace_with_2mm_gap": switch_brace_clear,
            "ir_aperture_avoids_backstop_brace_with_2mm_gap": emitter_brace_clear,
            "avoids_nominal_ir_hole_with_2mm_gap": ir_clear,
            "stop_displacement_inside_measured_travel": actuation,
            "ir_emitter_aperture_inside_backstop": emitter_inside,
        })
    independent_separation = (
        d["seat_pair_spacing_mm"]
        - (d["left_switch_body_width_mm"]
           + d["right_switch_body_width_mm"]) / 2 >= 2 * margin
    )
    actuation = all(
        x["stop_displacement_inside_measured_travel"] for x in checks
    )
    ir_emitter_within_backstop = all(
        x["ir_emitter_aperture_inside_backstop"] for x in checks
    )
    # The gauge is centered across the existing unpowered entry channel,
    # with its 54mm long dimension across the dock and 25mm depth along
    # the approach. This orientation is NOT proven for real pogo contacts.
    # Robot underside Z is measured from the desk surface, not from the
    # dock floor; the printed dock base thickness is part of the envelope.
    carrier_x0 = (width - contact["carrier_length_mm"]) / 2
    carrier_x1 = (width + contact["carrier_length_mm"]) / 2
    carrier_y0 = (d["contact_center_y_mm"]
                  - contact["carrier_depth_mm"] / 2)
    carrier_y1 = (d["contact_center_y_mm"]
                  + contact["carrier_depth_mm"] / 2)
    carrier_top_z = (
        geometry["dock_base_top_z_mm"] + contact["carrier_height_mm"]
    )
    in_rail_channel = (
        carrier_x0 >= geometry["clear_channel_x_min_mm"] + margin
        and carrier_x1 <= geometry["clear_channel_x_max_mm"] - margin
    )
    before_backstop = (
        carrier_y0 >= margin
        and carrier_y1 + margin <= geometry["backstop_front_y_mm"]
    )
    # The floor carrier cannot overlap the full-width reinforcing brace.
    before_brace = carrier_y1 + margin <= geometry["backstop_brace_front_y_mm"]
    fits_under_robot = (
        carrier_top_z + d["required_contact_top_gap_mm"]
        <= d["robot_underside_z_at_stop_mm"]
    )
    gap_is_measured = d["required_contact_top_gap_mm"] >= 2
    contact_floor_possible = (
        in_rail_channel and before_backstop and before_brace
        and fits_under_robot and gap_is_measured
    )
    contact_floor = {
        "source_gauge_only": True,
        "source_carrier_x_mm": [carrier_x0, carrier_x1],
        "source_carrier_y_mm": [carrier_y0, carrier_y1],
        "source_carrier_top_z_mm": carrier_top_z,
        "inside_clear_channel_with_2mm_margin": in_rail_channel,
        "ahead_of_backstop_with_2mm_margin": before_backstop,
        "ahead_of_backstop_brace_with_2mm_margin": before_brace,
        "under_measured_robot_with_required_gap": fits_under_robot,
        "required_contact_gap_at_least_2mm": gap_is_measured,
        "actual_pogo_body_and_spring_travel_verified": False,
        "physical_contact_mate_verified": False,
        "electrical_contact_selected": False,
    }
    fits = (
        contact_floor_possible and
        all(c["within_backstop_with_2mm_web"]
            and c["avoids_apriltag_paper_with_2mm_gap"]
            and c["avoids_backstop_brace_with_2mm_gap"]
            and c["ir_aperture_avoids_backstop_brace_with_2mm_gap"]
            and c["avoids_nominal_ir_hole_with_2mm_gap"]
            for c in checks)
        and independent_separation and actuation
        and ir_emitter_within_backstop
    )
    return {
        "dock_id": d["dock_id"],
        "cad_source_sha256": geometry["source_sha256"],
        "contact_cad_source_sha256": contact["source_sha256"],
        "source_only_layout_possible": fits,
        "contact_floor_layout_possible": contact_floor_possible,
        "unpowered_contact_floor_layout": contact_floor,
        "switch_pair_separately_located": independent_separation,
        "stop_displacement_inside_measured_travel": actuation,
        "ir_emitter_aperture_inside_backstop": ir_emitter_within_backstop,
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


def blank_template(dock_id: int, *, cad: Path = CAD,
                   contact_cad: Path = CONTACT_CAD) -> dict:
    """Create the real-source contract without fabricating any measurement."""
    if type(dock_id) is not int or not 1 <= dock_id <= 5:
        raise ValueError("An actual numbered physical dock ID is required")
    return {
        "dock_id": dock_id,
        "cad_source_sha256": dock_constants(cad)["source_sha256"],
        "contact_cad_source_sha256": contact_constants(contact_cad)["source_sha256"],
        **{field: None for field in NUMERICS},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--measurements", type=Path)
    mode.add_argument("--template-for-dock", type=int, choices=range(1, 6),
                      help="Emit a blank source-pinned measurement form")
    parser.add_argument("--output", type=Path,
                        help="Write new template only; never overwrite evidence")
    args = parser.parse_args()
    if args.template_for_dock is not None:
        content = json.dumps(blank_template(args.template_for_dock), indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as sink:
                sink.write(content)
        else:
            print(content, end="")
        return
    if args.output:
        parser.error("--output only supports blank template generation")
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
