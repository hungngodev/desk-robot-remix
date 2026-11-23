// One source-identified GY-530 PCB FIT COUPON, not a desk-safety mounting bracket.
// ElectroPeak SEN-19-006 states body outline 10.5 x 13.3 mm. No verified PCB
// thickness, lens center, through-hole locations or signal pad orientation.
// Original CC0 source. Print a coupon and measure the ACTUAL part.
$fn = 48;
part = "vl53l0x_gy530_fit_gauge";
board_x = 10.5;
board_y = 13.3;
fit_each_side = 0.35;
wall = 2.0;
base = 1.5;
pocket_depth = 2.8; // nonbinding sample ONLY; actual carrier PCB unknown
module vl53l0x_gy530_fit_gauge() {
    x = board_x + 2*fit_each_side;
    y = board_y + 2*fit_each_side;
    assert(x < 14 && y < 18);
    assert(fit_each_side >= 0.2 && fit_each_side <= 0.8);
    // A source fit cup with a zero-thickness floor or paper-thin perimeter
    // cannot safely measure this nominal board's actual XY footprint.
    assert(wall >= 2 && wall <= 6,
           "GY530 coupon side wall below printable minimum");
    assert(base >= 1.5 && base <= 6,
           "GY530 coupon floor below printable minimum");
    assert(pocket_depth >= 2 && pocket_depth <= 10,
           "GY530 coupon depth outside meaningful sample bounds");
    difference() {
        cube([x+2*wall, y+2*wall, base+pocket_depth]);
        // Open upper pocket measures printed XY fit, NOT lens or bolts.
        translate([wall,wall,base]) cube([x,y,pocket_depth+1]);
        // Visible notch allows gentle removal WITHOUT touching optical lens.
        translate([0,(y+2*wall)/2-2.0,base])
            cube([wall+0.1,4.0,pocket_depth+1]);
    }
}

/*
 * Free standing, UNPOWERED downward optical height trial for the selected
 * nominal GY-530 carrier. Only the board's 10.5 x 13.3 mm outer drawing
 * is known. Its actual lens extension, orientation, internal lens center,
 * PCB thickness, wiring and floor standoff are NOT measured.
 *
 * This tapered hollow support leaves an optical opening to the desk. A
 * real board can rest on its top ring during stationary, operator attended
 * checks. There is intentionally NO PCB clamp or chassis mounting feature;
 * it must never be used for driving or to certify cliff clearance.
 *
 * Heights 35/45/55 mm describe the board support rim, NOT lens standoff.
 */
module vl53l0x_gy530_height_trial(height_mm) {
    bottom_x = 36;
    bottom_y = 39;
    inner_bottom_x = 30;
    inner_bottom_y = 33;
    top_x = board_x + 6;
    top_y = board_y + 6;
    inner_top_x = board_x - 3;
    inner_top_y = board_y - 3;
    assert(height_mm >= 35 && height_mm <= 55,
           "Height trial outside measured candidate range");
    assert(bottom_x - inner_bottom_x >= 6 && bottom_y - inner_bottom_y >= 6,
           "Height trial base wall below printable minimum");
    assert(top_x - inner_top_x >= 8 && top_y - inner_top_y >= 8,
           "Height trial top ring below printable minimum");
    assert(inner_top_x > 6 && inner_top_y > 9,
           "Height trial optical opening too narrow");
    difference() {
        hull() {
            translate([-bottom_x/2,-bottom_y/2,0])
                cube([bottom_x,bottom_y,3]);
            translate([-top_x/2,-top_y/2,height_mm-3])
                cube([top_x,top_y,3]);
        }
        hull() {
            translate([-inner_bottom_x/2,-inner_bottom_y/2,-1])
                cube([inner_bottom_x,inner_bottom_y,4]);
            translate([-inner_top_x/2,-inner_top_y/2,height_mm-3])
                cube([inner_top_x,inner_top_y,4]);
        }
    }
}
if(part == "vl53l0x_gy530_fit_gauge") vl53l0x_gy530_fit_gauge();
else if(part == "vl53l0x_gy530_height_trial_035") vl53l0x_gy530_height_trial(35);
else if(part == "vl53l0x_gy530_height_trial_045") vl53l0x_gy530_height_trial(45);
else if(part == "vl53l0x_gy530_height_trial_055") vl53l0x_gy530_height_trial(55);
else assert(false,"Unknown coupon");
