// One-robot MG90S servo pocket fit coupon for original Bluino SMARS gripper.
// Does not edit or redistribute the original gripper/forklift STLs.
// DEFAULT DIMENSIONS ARE NOMINAL ONLY. CALIPER-MEASURE YOUR ACTUAL MG90S.
$fn=32;
case_length_mm = 23.0;
case_width_mm = 12.2;
wall_mm = 2.5;
floor_mm = 2.0;
total_height_mm = 8.0;
spacing_mm = 8.0;
clearances_mm = [0.15, 0.30, 0.45, 0.60];
assert(case_length_mm > 0 && case_width_mm > 0, "Measure actual servo case first");
assert(wall_mm >= 2 && floor_mm >= 1.5 && total_height_mm > floor_mm);
module fit_gauge(clearance_mm) {
    length = case_length_mm + 2*wall_mm;
    width = case_width_mm + 2*wall_mm;
    difference() {
        cube([length, width, total_height_mm]);
        translate([wall_mm-clearance_mm/2,
                   wall_mm-clearance_mm/2, floor_mm])
            cube([case_length_mm+clearance_mm,
                  case_width_mm+clearance_mm,
                  total_height_mm-floor_mm+0.1]);
    }
}
for (i=[0:len(clearances_mm)-1]) {
    translate([i*(case_length_mm+2*wall_mm+spacing_mm),0,0])
        fit_gauge(clearances_mm[i]);
}
