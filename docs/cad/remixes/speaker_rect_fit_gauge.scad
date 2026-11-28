// Source-based FIT COUPON ONLY for active 8-ohm 2W 20x16x4.7mm
// Challenge Electronics CS20-02P110-04-1X. Original CC0 adapter.
// Not a speaker enclosure, soundbox, or proof of thermal/acoustic fit.
$fn=48;
part="speaker_rect_fit_gauge";
speaker_l=20;
speaker_w=16;
speaker_h=4.7;
speaker_fit_xy=0.35; // nominal each side, adjust only after a physical coupon
speaker_wall=2.2;
speaker_base=2.0;
// Nominal reference for the sealed-back 1cc speaker requirement.
// No wire feedthrough is cut: an unsealed solder-lead notch would defeat
// the air chamber. Real gasket, wire potting, speaker intrusion and head fit
// still REQUIRE physical assembly/leak/thermal/acoustic qualification.
// Cup front screw pattern intentionally matches the widened 36x32 grille.
speaker_chamber_border=8;
speaker_chamber_hole_edge=3.5;
speaker_chamber_bolt_d=2.35;
speaker_chamber_back_wall=2.4;
speaker_chamber_depth=9;
speaker_chamber_min_air_cc=1.0;
module speaker_rect_fit_gauge() {
    pocket_l=speaker_l+2*speaker_fit_xy;
    pocket_w=speaker_w+2*speaker_fit_xy;
    outer_l=pocket_l+2*speaker_wall;
    outer_w=pocket_w+2*speaker_wall;
    total_h=speaker_base+speaker_h+0.4;
    assert(speaker_l==20 && speaker_w==16 && speaker_h>=4.7);
    assert(speaker_fit_xy>=0.2 && speaker_fit_xy<=0.8);
    assert(speaker_wall>=2 && speaker_base>=1.5,
           "Speaker fit cup wall or floor below printable minimum");
    difference() {
        cube([outer_l,outer_w,total_h]);
        // One rectangular test pocket, intentionally OPEN TOP.
        translate([speaker_wall,speaker_wall,speaker_base])
            cube([pocket_l,pocket_w,speaker_h+1]);
        // Wire solder-pad service notch. Connector routing is NOT final.
        translate([outer_l-speaker_wall-0.1,outer_w/2-2.5,speaker_base])
            cube([speaker_wall+0.2,5,speaker_h+1]);
    }
}
module speaker_rear_chamber_reference() {
    // Gross geometric air cavity minus an ENTIRE 20x16x4.7 mm speaker
    // rectangular envelope is a conservative paper air-volume bound.
    // It is not the actual manufacturer acoustic volume until sealed and
    // physically measured; not permission to omit solder-pad clearance.
    inner_l=speaker_l+2*speaker_fit_xy;
    inner_w=speaker_w+2*speaker_fit_xy;
    outer_l=speaker_l+2*speaker_chamber_border;
    outer_w=speaker_w+2*speaker_chamber_border;
    total_h=speaker_chamber_back_wall+speaker_chamber_depth;
    conservative_air_mm3=inner_l*inner_w*speaker_chamber_depth
                         -speaker_l*speaker_w*speaker_h;
    assert(speaker_l==20 && speaker_w==16 && speaker_h>=4.7);
    assert(speaker_fit_xy>=0.2 && speaker_fit_xy<=0.8);
    assert(speaker_chamber_min_air_cc>=1,
           "Speaker chamber minimum air requirement cannot be reduced below 1cc");
    assert(speaker_chamber_bolt_d>=2,
           "Speaker chamber M2 bore is undersized");
    assert(conservative_air_mm3 >= speaker_chamber_min_air_cc*1000,
           "Speaker nominal net air volume below 1cc");
    assert(speaker_chamber_back_wall>=2 && speaker_chamber_border>=6,
           "Speaker chamber back wall or flange too thin");
    assert(speaker_chamber_hole_edge-speaker_chamber_bolt_d/2>=2,
           "Speaker chamber bolt breaches outer wall");
    assert(outer_l/2-speaker_chamber_hole_edge-speaker_chamber_bolt_d/2
           -inner_l/2>=2 &&
           outer_w/2-speaker_chamber_hole_edge-speaker_chamber_bolt_d/2
           -inner_w/2>=2,
           "Speaker chamber bolt breaches gasket land");
    difference() {
        cube([outer_l,outer_w,total_h]);
        translate([(outer_l-inner_l)/2,(outer_w-inner_w)/2,
                   speaker_chamber_back_wall])
            cube([inner_l,inner_w,speaker_chamber_depth+1]);
        for(x=[speaker_chamber_hole_edge,
               outer_l-speaker_chamber_hole_edge],
            y=[speaker_chamber_hole_edge,
               outer_w-speaker_chamber_hole_edge])
            translate([x,y,total_h/2])
                cylinder(h=total_h+1,d=speaker_chamber_bolt_d,center=true);
    }
}
if(part=="speaker_rect_fit_gauge") speaker_rect_fit_gauge();
else if(part=="speaker_rear_chamber_reference")
    speaker_rear_chamber_reference();
else assert(false,"Unknown fit part");
