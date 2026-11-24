// Passive one-robot docking alignment fit, never an energized charging cradle.
// CC0 original part. Nominal dimensions are an example, not measured robot fit.
$fn = 32;
part = "dock_passive_fit";
track_outer_width_mm = 96; // replace with measured real track outer width
side_clearance_each_mm = 2; // change after real printed clearance trial
base_length_mm = 138;
base_thickness_mm = 3;
guide_wall_mm = 5;
guide_run_mm = 107;
entry_flare_each_mm = 7;
guide_height_mm = 12;
backstop_thickness_mm = 5;
backstop_height_mm = 90;
backstop_brace_depth_mm = 8;
backstop_brace_height_mm = 10;
wall_outside_margin_mm = 8;
// The printable AprilTag must have a WHITE quiet border around the measured
// black marker. Registration pocket is on the side facing the approaching pet.
tag_black_side_mm = 60;
tag_white_margin_each_mm = 5;
tag_paper_slack_each_mm = 0.6;
tag_recess_depth_mm = 0.8;
tag_bottom_z_mm = 16;
tag_paper_side_mm = tag_black_side_mm + 2 * tag_white_margin_each_mm;
tag_pocket_side_mm = tag_paper_side_mm + 2 * tag_paper_slack_each_mm;
channel_mm = track_outer_width_mm + 2 * side_clearance_each_mm;
inner_wall_x = guide_wall_mm + wall_outside_margin_mm;
outside_width_mm = channel_mm + 2 * inner_wall_x;
backstop_front_y_mm = base_length_mm - backstop_thickness_mm;
backstop_brace_front_y_mm = backstop_front_y_mm - backstop_brace_depth_mm;
// The reversible coupon includes the 37 mm flare and straight guide.
entry_coupon_length_mm = 48;
// Unpowered IR pair LOCATION TEST: not an emitter holder or final beam aim.
// Both transmitter carrier, lens diameter and mounting angles are unmeasured.
ir_pair_spacing_mm = 98; // provisional symmetric markers at x14/112
ir_probe_bore_d_mm = 5.5; // nominal 5 mm component clearance TEST only
ir_coupon_height_mm = 16;
ir_coupon_thickness_mm = 3;
ir_min_tag_web_mm = 3;
assert(track_outer_width_mm > 40 && track_outer_width_mm < 200);
assert(side_clearance_each_mm >= 0.5 && side_clearance_each_mm < 8);
assert(base_length_mm > guide_run_mm + backstop_thickness_mm);
assert(backstop_brace_depth_mm > 0 && backstop_brace_front_y_mm > guide_run_mm);
assert(backstop_brace_height_mm > 0 && backstop_brace_height_mm <= backstop_height_mm);
assert(entry_flare_each_mm > 0 && entry_flare_each_mm < inner_wall_x);
assert(entry_coupon_length_mm > 37 && entry_coupon_length_mm < guide_run_mm);
// Geometry invariants shared by the full dock and its entry coupon.
// The nominal channel must be measured between the INNER faces of the rails.
assert(abs((outside_width_mm - 2 * inner_wall_x) - channel_mm) < 0.001);
assert(inner_wall_x - guide_wall_mm - entry_flare_each_mm >= 0);
assert(guide_wall_mm > 0 && guide_run_mm > 37);
assert(tag_black_side_mm >= 10 && tag_black_side_mm <= 75);
assert(tag_white_margin_each_mm >= 4 && tag_white_margin_each_mm <= 10);
assert(tag_paper_slack_each_mm >= 0.25 && tag_paper_slack_each_mm <= 1.5);
assert(tag_recess_depth_mm >= 0.4 && tag_recess_depth_mm < backstop_thickness_mm - 2);
assert(tag_pocket_side_mm < outside_width_mm - 2 * inner_wall_x);
assert(tag_bottom_z_mm >= base_thickness_mm + backstop_brace_height_mm + 2);
assert(tag_bottom_z_mm + tag_pocket_side_mm + 3 <= base_thickness_mm + backstop_height_mm);

module one_side_rail() {
    // Wider entry mouth is tapered into a measured track width.
    linear_extrude(height = guide_height_mm)
        polygon(points=[
            // The inner face sets the measured channel width. Both rail
            // faces flare outward at entry while keeping wall thickness.
            [inner_wall_x - guide_wall_mm - entry_flare_each_mm, 0],
            [inner_wall_x - entry_flare_each_mm, 0],
            [inner_wall_x, 37],
            [inner_wall_x, guide_run_mm],
            [inner_wall_x - guide_wall_mm, guide_run_mm],
            [inner_wall_x - guide_wall_mm, 37]
        ]);
}

module dock_rail_section() {
    union() {
        cube([outside_width_mm, base_length_mm, base_thickness_mm]);
        translate([0,0,base_thickness_mm]) one_side_rail();
        translate([outside_width_mm,0,base_thickness_mm])
            mirror([1,0,0]) one_side_rail();
    }
}

module dock_passive_fit() {
    // Recessed AprilTag paper with >2 mm of unpowered backing.
    difference() {
        union() {
            dock_rail_section();
            translate([0,backstop_front_y_mm,base_thickness_mm])
                cube([outside_width_mm,backstop_thickness_mm,backstop_height_mm]);
            translate([0,backstop_brace_front_y_mm,base_thickness_mm])
                cube([outside_width_mm,backstop_brace_depth_mm,backstop_brace_height_mm]);
        }
        translate([(outside_width_mm - tag_pocket_side_mm) / 2,
                   backstop_front_y_mm - 0.01, tag_bottom_z_mm])
            cube([tag_pocket_side_mm, tag_recess_depth_mm + 0.01,
                  tag_pocket_side_mm]);
    }
}

module dock_rail_entry_coupon() {
    // Unpowered entry guide only; no AprilTag, stop or charging contacts.
    // Reuses the exact full-dock guide geometry.
    intersection() {
        dock_rail_section();
        cube([outside_width_mm, entry_coupon_length_mm,
              base_thickness_mm + guide_height_mm]);
    }
}

module dock_ir_pair_position_coupon() {
    // Flat 1:1 reversible layout jig. Two independent beacon beam centers
    // sit outside the printed AprilTag's required white quiet border.
    // No LEDs, drivers, current-limiting resistor, charging, terminal travel,
    // receiver mounting, or optical baffles are qualified by this print.
    assert(ir_pair_spacing_mm > 0 && ir_pair_spacing_mm < outside_width_mm);
    assert(ir_probe_bore_d_mm > 1 && ir_probe_bore_d_mm < 15);
    assert(ir_coupon_thickness_mm >= 2 && ir_coupon_height_mm >= 10);
    assert(ir_min_tag_web_mm >= 3);
    assert(ir_pair_spacing_mm / 2 - ir_probe_bore_d_mm / 2 >=
           tag_pocket_side_mm / 2 + ir_min_tag_web_mm,
           "IR aperture overlaps AprilTag quiet paper margin");
    assert(outside_width_mm / 2 - ir_pair_spacing_mm / 2 -
           ir_probe_bore_d_mm / 2 >= ir_min_tag_web_mm,
           "IR aperture breaches outer dock edge");
    assert(ir_coupon_height_mm / 2 - ir_probe_bore_d_mm / 2 >= ir_min_tag_web_mm,
           "IR aperture breaches coupon long edge");
    difference() {
        cube([outside_width_mm, ir_coupon_height_mm,
              ir_coupon_thickness_mm]);
        for (x = [outside_width_mm/2-ir_pair_spacing_mm/2,
                  outside_width_mm/2+ir_pair_spacing_mm/2])
            translate([x, ir_coupon_height_mm/2, -0.1])
                cylinder(h=ir_coupon_thickness_mm+0.2,
                         d=ir_probe_bore_d_mm);
    }
}

if (part == "dock_passive_fit") dock_passive_fit();
else if (part == "dock_rail_entry_coupon") dock_rail_entry_coupon();
else if (part == "dock_ir_pair_position_coupon") dock_ir_pair_position_coupon();
else assert(false, "Unknown passive dock fit part");
