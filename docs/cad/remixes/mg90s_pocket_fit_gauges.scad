// One-robot MG90S servo pocket fit coupon for original Bluino SMARS gripper.
// Does not edit or redistribute the original gripper/forklift STLs.
// DEFAULT DIMENSIONS ARE NOMINAL ONLY. CALIPER-MEASURE YOUR ACTUAL MG90S.
$fn=32;
part = "mg90s_four_cup_layout";
case_length_mm = 23.0;
case_width_mm = 12.2;
wall_mm = 2.5;
floor_mm = 2.0;
total_height_mm = 8.0;
spacing_mm = 8.0;
clearances_mm = [0.15, 0.30, 0.45, 0.60];
assert(case_length_mm > 0 && case_width_mm > 0, "Measure actual servo case first");
assert(wall_mm >= 2 && floor_mm >= 1.5 && total_height_mm >= floor_mm + 3);
assert(spacing_mm >= 2, "Servo fit coupons need printable separation");
assert(len(clearances_mm) >= 1 && len(clearances_mm) <= 8,
       "Servo fit coupon count must be bounded");
module fit_gauge(clearance_mm, tick_count) {
    // The pocket expands by half the requested clearance on each wall.
    // The prior script accepted an arbitrarily large clearance, deleting
    // the printed wall while still appearing to produce a valid fit test.
    assert(is_num(clearance_mm) &&
           clearance_mm >= 0.1 && clearance_mm <= 1.5,
           "Servo pocket clearance must be measured and positive");
    assert(wall_mm-clearance_mm/2 >= 2,
           "Servo pocket clearance leaves insufficient printable wall");
    assert(is_num(tick_count) && tick_count >= 1 && tick_count <= 8,
           "Identify one to eight distinct printed clearance coupons");
    length = case_length_mm + 2*wall_mm;
    width = case_width_mm + 2*wall_mm;
    // Tactile, integral outside-wall ticks identify ascending clearances
    // after individually exported coupons are separated from file labels.
    // Adding material outside the negative Y face never reduces the
    // calibrated servo pocket, minimum walls, or bottom thickness.
    union() {
        difference() {
            cube([length, width, total_height_mm]);
            translate([wall_mm-clearance_mm/2,
                       wall_mm-clearance_mm/2, floor_mm])
                cube([case_length_mm+clearance_mm,
                      case_width_mm+clearance_mm,
                      total_height_mm-floor_mm+0.1]);
        }
        // Also preserve the historical configurable 1..8 cup layout.
        assert(4 + (tick_count-1)*2.45 + 1.5 <= length-2,
               "Servo case too short for legible clearance markings");
        for (tick=[0:tick_count-1])
            translate([4 + tick*2.45, -0.6, floor_mm])
                cube([1.5, 0.9, 2.5]);
    }
}
// Export each coupon as an independent single-solid STL to keep the
// shared print verifier's closed, connected mesh policy. Historical
// four-cup layout remains available for manually printing the set.
if (part == "mg90s_four_cup_layout") {
    for (i=[0:len(clearances_mm)-1]) {
        translate([i*(case_length_mm+2*wall_mm+spacing_mm),0,0])
            fit_gauge(clearances_mm[i], i+1);
    }
} else if (part == "mg90s_fit_015") fit_gauge(0.15, 1);
else if (part == "mg90s_fit_030") fit_gauge(0.30, 2);
else if (part == "mg90s_fit_045") fit_gauge(0.45, 3);
else if (part == "mg90s_fit_060") fit_gauge(0.60, 4);
else assert(false, "Unknown MG90S fit coupon");
