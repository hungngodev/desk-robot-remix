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
module speaker_rect_fit_gauge() {
    pocket_l=speaker_l+2*speaker_fit_xy;
    pocket_w=speaker_w+2*speaker_fit_xy;
    outer_l=pocket_l+2*speaker_wall;
    outer_w=pocket_w+2*speaker_wall;
    total_h=speaker_base+speaker_h+0.4;
    assert(speaker_l==20 && speaker_w==16 && speaker_h>=4.7);
    assert(speaker_fit_xy>=0.2 && speaker_fit_xy<=0.8);
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
if(part=="speaker_rect_fit_gauge") speaker_rect_fit_gauge();
else assert(false,"Unknown fit part");
