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
if(part == "vl53l0x_gy530_fit_gauge") vl53l0x_gy530_fit_gauge();
else assert(false,"Unknown coupon");
