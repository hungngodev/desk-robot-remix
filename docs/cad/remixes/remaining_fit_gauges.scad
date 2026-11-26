// Desk robot remaining mechanical FIT TESTS. Units mm, original CC0 source.
// Not a finished chassis or an energized dock. Set actual measured parts.
$fn = 48;
part = "battery_boost_tray";
fit_xy = 0.4;
m3_clearance = 3.4;

// Published protected LPHD7430085 body: 86 x 30 x 7.4 mm before leads.
// https://www.lipoly-battery.com/high-rate-discharge-lipoly-battery-lphd7430085-5a-3-7v-2000mah-7-4wh/
// Quoted connector is Molex 43645-0300, NOT JST-PH. The complete power
// package, connector exit and safe lead bend are still UNMEASURED.
// This gauge only excludes undersized layouts, not a full power enclosure.
candidate_pack_body_l_mm = 86;
candidate_pack_body_w_mm = 30;
candidate_pack_body_h_mm = 7.4;
power_l = 86;
power_w = 35;
power_h = 14;
wall = 2.4;
base = 2.8;
tray_strap_slot_w = 3.2;
// Provisional external tab footprint, also consumed by the A4 overlay.
tray_tab_l_mm = 8;
tray_tab_w_mm = 9;
tray_tab_offset_mm = 5;

// Dummy charging connector sizes only. Keep these printed parts NONCONDUCTIVE.
contact_centers_mm = 20;
contact_outer_d_mm = 4;
contact_pocket_depth_mm = 5;
contact_carrier_l = 54;
contact_carrier_w = 25;
contact_carrier_h = 9;

// Actual test reference thickness. Prints a replaceable jaw calibration coupon.
jaw_reference_thickness_mm = 2;
jaw_reference_width_mm = 12;
jaw_reference_depth_mm = 12;

module battery_boost_tray() {
    l = power_l + 2*fit_xy + 2*wall;
    w = power_w + 2*fit_xy + 2*wall;
    h = power_h + base;
    assert(power_l > 25 && power_l < 150);
    assert(power_l >= candidate_pack_body_l_mm,
           "Battery tray shorter than selected candidate pack body");
    assert(power_w >= candidate_pack_body_w_mm && power_h >= candidate_pack_body_h_mm,
           "Battery tray narrower or shallower than selected candidate pack body");
    assert(power_w > 12 && power_w < 100);
    assert(power_h > 4 && power_h < 60);
    assert(fit_xy >= 0.2 && wall >= 2 && base >= 2,
           "Battery tray clearance, wall or floor below printable minimum");
    assert(m3_clearance >= 3 && tray_tab_l_mm > m3_clearance &&
           tray_tab_w_mm > m3_clearance);
    assert(min(tray_tab_l_mm, tray_tab_w_mm) - m3_clearance >= 4,
           "Battery tray mounting tab leaves insufficient M3 web");
    assert(tray_strap_slot_w >= 2 && l/3-tray_strap_slot_w >= 2,
           "Battery tray strap openings missing or intersecting");
    assert(tray_tab_offset_mm > 0 && tray_tab_offset_mm + tray_tab_w_mm <= w);
    difference() {
        union() {
            cube([l, w, base]);
            cube([wall, w, h]);
            translate([l-wall,0,0]) cube([wall, w, h]);
            cube([l, wall, h]);
            translate([0,w-wall,0]) cube([l, wall, h]);
            // External mounting tabs, not battery screw holes.
            translate([-tray_tab_l_mm, tray_tab_offset_mm, 0])
                cube([tray_tab_l_mm, tray_tab_w_mm, base]);
            translate([l, w-tray_tab_offset_mm-tray_tab_w_mm, 0])
                cube([tray_tab_l_mm, tray_tab_w_mm, base]);
        }
        // Lift-out / cable slots only; NOT qualified connector passage or strain relief.
        translate([l/2-5,-1,base+2]) cube([10,wall+2, h]);
        translate([-1,w/2-4,base+3]) cube([wall+2,8,h]);
        translate([-tray_tab_l_mm/2,tray_tab_offset_mm+tray_tab_w_mm/2,base/2])
            cylinder(h=base+1,d=m3_clearance,center=true);
        translate([l+tray_tab_l_mm/2,w-tray_tab_offset_mm-tray_tab_w_mm/2,base/2])
            cylinder(h=base+1,d=m3_clearance,center=true);
        // Two accessible strap openings through the base.
        for(x=[l/3,2*l/3])
            translate([x,w/2,base/2])
                cube([tray_strap_slot_w,w-2*wall-5,base+1],center=true);
    }
}

module dock_contact_recess_gauge() {
    assert(contact_centers_mm > 8 && contact_centers_mm < contact_carrier_l-14);
    assert(contact_outer_d_mm > 1 && contact_outer_d_mm < 10);
    assert(contact_pocket_depth_mm > 1 && contact_pocket_depth_mm < contact_carrier_h);
    // The two recessed contact pockets must not break into the adjacent M3
    // mounting bore at either end. This is a printable nonenergized gauge,
    // not a safe or selected electrical contact holder.
    contact_radius_mm = (contact_outer_d_mm + fit_xy) / 2;
    minimum_pocket_floor_mm = 2;
    minimum_side_wall_mm = 2;
    assert(contact_carrier_h - contact_pocket_depth_mm >= minimum_pocket_floor_mm,
           "Contact recess leaves insufficient insulated floor");
    assert(contact_carrier_w / 2 - contact_radius_mm >= minimum_side_wall_mm,
           "Contact recess breaches side wall");
    bolt_radius_mm = m3_clearance / 2;
    bolt_center_x_mm = contact_carrier_l / 2 - 5;
    contact_center_x_mm = contact_centers_mm / 2;
    minimum_bridge_mm = 2;
    assert(bolt_center_x_mm - contact_center_x_mm >=
           bolt_radius_mm + contact_radius_mm + minimum_bridge_mm,
           "Contact recess would intersect or thin the mounting web");
    difference() {
        translate([-contact_carrier_l/2,-contact_carrier_w/2,0])
            cube([contact_carrier_l, contact_carrier_w, contact_carrier_h]);
        // Recessed NONENERGIZED connector fit pockets. No contact polarity.
        for(x=[-contact_centers_mm/2, contact_centers_mm/2])
            translate([x,0,contact_carrier_h-contact_pocket_depth_mm])
                cylinder(h=contact_pocket_depth_mm+1,d=contact_outer_d_mm+fit_xy);
        for(x=[-contact_carrier_l/2+5,contact_carrier_l/2-5])
            translate([x,0,contact_carrier_h/2])
                cylinder(h=contact_carrier_h+1,d=m3_clearance,center=true);
        // Sample cable clearance only; do not power any contacts with this part.
        translate([-3,contact_carrier_w/2-3,0]) cube([6,4,3]);
    }
}

module jaw_calibration_coupon() {
    assert(jaw_reference_thickness_mm >= 0.8 && jaw_reference_thickness_mm <= 15);
    assert(jaw_reference_width_mm >= 6 && jaw_reference_depth_mm >= 6);
    // Print flat, put it between the unpowered jaws, then measure actual
    // servo angle + tactile ADC response before applying any force limits.
    cube([jaw_reference_width_mm,jaw_reference_depth_mm,
          jaw_reference_thickness_mm]);
}

if(part == "battery_boost_tray") battery_boost_tray();
else if(part == "dock_contact_recess_gauge") dock_contact_recess_gauge();
else if(part == "jaw_calibration_coupon") jaw_calibration_coupon();
else assert(false,"Unknown printable fit gauge");
