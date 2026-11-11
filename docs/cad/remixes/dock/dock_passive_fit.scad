// Passive one-robot docking alignment fit, never an energized charging cradle.
// CC0 original part. Nominal dimensions are an example, not measured robot fit.
$fn = 32;
track_outer_width_mm = 96; // replace with measured real track outer width
side_clearance_each_mm = 2; // change after real printed clearance trial
base_length_mm = 138;
base_thickness_mm = 3;
guide_wall_mm = 5;
guide_run_mm = 107;
entry_flare_each_mm = 7;
guide_height_mm = 12;
backstop_thickness_mm = 5;
backstop_height_mm = 78;
wall_outside_margin_mm = 8;
channel_mm = track_outer_width_mm + 2 * side_clearance_each_mm;
inner_wall_x = guide_wall_mm + wall_outside_margin_mm;
outside_width_mm = channel_mm + 2 * inner_wall_x;
assert(track_outer_width_mm > 40 && track_outer_width_mm < 200);
assert(side_clearance_each_mm >= 0.5 && side_clearance_each_mm < 8);
assert(base_length_mm > guide_run_mm + backstop_thickness_mm);
assert(entry_flare_each_mm > 0 && entry_flare_each_mm < inner_wall_x);

module one_side_rail() {
    // Wider entry mouth is tapered into a measured track width.
    linear_extrude(height = guide_height_mm)
        polygon(points=[
            [0, 0],
            [inner_wall_x - entry_flare_each_mm, 0],
            [inner_wall_x, 37],
            [inner_wall_x, guide_run_mm],
            [inner_wall_x - guide_wall_mm, guide_run_mm],
            [inner_wall_x - guide_wall_mm, 37]
        ]);
}

union() {
    cube([outside_width_mm, base_length_mm, base_thickness_mm]);
    translate([0,0,base_thickness_mm]) one_side_rail();
    translate([outside_width_mm,0,base_thickness_mm])
        mirror([1,0,0]) one_side_rail();
    translate([0,base_length_mm - backstop_thickness_mm,
               base_thickness_mm])
        cube([outside_width_mm,backstop_thickness_mm,backstop_height_mm]);
    translate([0,base_length_mm - backstop_thickness_mm - 8,
               base_thickness_mm])
        cube([outside_width_mm,8,10]);
}
