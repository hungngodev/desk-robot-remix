// ONE desk robot adapter kit. CC0 original code. Units mm.
// These are prototype adapter parts, not the finished merged robot assembly.
// Preserve the upstream licenses of original chassis, gripper, lift and head.
// Use openscad -o part.stl -D 'part="oled_bezel"' one_robot_adapter_kit.scad
$fn=48;
part="head_bridge";
fit_xy=.35;
m2_clearance_d=2.35;
m3_clearance_d=3.35;
head_bridge_x=52;
head_bridge_y=46;
head_mount_x=39;
head_mount_y=32;
head_wire_clearance=20;
// Selected pilot GY-530 (ElectroPeak SEN-19-006) nominal PCB outline.
// Lens center, holes, connector overhang and true mounting height UNMEASURED.
tof_pcb_w=10.5;
tof_pcb_h=13.3;
tof_lens_d=6;
oled_pcb_x=27;
oled_pcb_y=27;
oled_window_x=22;
oled_window_y=12;
// Exact active candidate envelope only; solder pads, leads and gasket
// still require a physical coupon before any sealed speaker chamber.
speaker_l=20;
speaker_w=16;
speaker_h=4.7;
// Preserve >=2 mm printable plastic between all M2 grille bores and
// both the nominal speaker/gasket pocket and outside free edges.
// Original 32x28 plate gave only 0.975 mm at the inner edge.
speaker_grille_border=8;
speaker_grille_hole_edge=3.5;
speaker_grille_min_web=2;
fsr_d=12;
dock_tag_black_square=60;
dock_mount_spacing=76;
// Minimum radial print web from M3 bolt bore to any free plate edge.
// Keeps the provisional hole pitch without claiming dock mount fit.
dock_tag_edge_web_mm=3;
// Dimensions above are placeholders until real hardware is measured.
module oval_slot(l=7,d=2.5,h=5){
  hull(){
    translate([-l/2,0,0]) cylinder(h=h,d=d,center=true);
    translate([ l/2,0,0]) cylinder(h=h,d=d,center=true);
  }
}
module head_bridge(){
  difference(){
    translate([0,0,1.5]) cube([head_bridge_x,head_bridge_y,3],center=true);
    translate([0,0,2]) cube([head_wire_clearance,head_wire_clearance,6],center=true);
    for(x=[-head_mount_x/2,head_mount_x/2],y=[-head_mount_y/2,head_mount_y/2])
      translate([x,y,2]) oval_slot(5,m3_clearance_d,7);
  }
}
module tof_adjustable(){
  base_x=tof_pcb_w+12; face_z=tof_pcb_h+7;
  difference(){
    union(){
      translate([0,0,1.5]) cube([base_x,19,3],center=true);
      translate([0,7.5,face_z/2]) cube([base_x,3,face_z],center=true);
      for(x=[-base_x/2+4,base_x/2-4])
        hull(){
          translate([x,3,3]) cube([3,9,3],center=true);
          translate([x,7.5,9]) cube([3,3,3],center=true);
        }
    }
    for(x=[-base_x/4,base_x/4])
      translate([x,-4,1.5]) rotate([0,0,90]) oval_slot(5,m2_clearance_d,7);
    translate([0,7.5,face_z/2+1]) rotate([90,0,0])
      cylinder(h=7,d=tof_lens_d+2,center=true);
    // No fake GY-530 PCB screw holes. The formerly assumed centers at
    // +/- (10.5/2 - 2) mm put both 6 mm slots THROUGH the optical aperture.
    // The actual carrier has no qualified mounting-hole coordinates yet.
    // This is an aperture/angle reference ONLY, not a retained sensor mount.
    // Design a measured carrier clamp or adapter after the pilot PCB arrives.
  }
}
module oled_bezel(){
  x=oled_pcb_x+8; y=oled_pcb_y+8;
  difference(){
    translate([0,0,1.5]) cube([x,y,3],center=true);
    translate([0,0,1.5])
      cube([oled_window_x+fit_xy,oled_window_y+fit_xy,5],center=true);
    for(xx=[-x/2+3,x/2-3],yy=[-y/2+3,y/2-3])
      translate([xx,yy,1.5]) cylinder(h=5,d=m2_clearance_d,center=true);
  }
}
module speaker_grille(){
  // Current fixed rectangular Challenge CS20-02P110-04-1X 8ohm 2W.
  // This is a PERFORATED FRONT PLATE only, not the 1cc sealed chamber.
  // Keep it dimensionally separate from the physical speaker pocket and
  // its solder-pad strain relief; do not reuse retired 20mm round grille.
  assert(speaker_l == 20 && speaker_w == 16 && speaker_h == 4.7);
  panel_x=speaker_l+2*speaker_grille_border;
  panel_y=speaker_w+2*speaker_grille_border;
  assert(speaker_grille_min_web>=2);
  assert(speaker_grille_hole_edge-m2_clearance_d/2 >=
         speaker_grille_min_web,
         "Speaker grille hole breaches outside printable web");
  assert(panel_x/2-speaker_grille_hole_edge-m2_clearance_d/2
         -(speaker_l/2+fit_xy) >= speaker_grille_min_web &&
         panel_y/2-speaker_grille_hole_edge-m2_clearance_d/2
         -(speaker_w/2+fit_xy) >= speaker_grille_min_web,
         "Speaker grille hole breaches gasket/pocket printable web");
  difference(){
    translate([0,0,1.5]) cube([panel_x,panel_y,3],center=true);
    for(x=[-7.5,-3.75,0,3.75,7.5],y=[-5,0,5])
      if(abs(x)+1.2 < speaker_l/2 && abs(y)+1.2 < speaker_w/2)
        translate([x,y,1.5]) cylinder(h=6,d=2.4,center=true);
    for(x=[-panel_x/2+speaker_grille_hole_edge,
            panel_x/2-speaker_grille_hole_edge],
        y=[-panel_y/2+speaker_grille_hole_edge,
            panel_y/2-speaker_grille_hole_edge])
      translate([x,y,1.5]) cylinder(h=5,d=m2_clearance_d,center=true);
  }
}
module fsr_jaw_pocket(){
  x=fsr_d+10; y=fsr_d+10;
  difference(){
    union(){
      translate([0,0,1.25]) cube([x,y,2.5],center=true);
      translate([0,0,2.4]) difference(){
        cylinder(h=1.5,d=fsr_d+3);
        cylinder(h=2,d=fsr_d+fit_xy);
      }
    }
    translate([0,0,3.3]) cylinder(h=3,d=fsr_d+fit_xy,center=true);
    translate([0,-y/2+2,2.5]) cube([3.5,9,5],center=true);
    for(xx=[-x/2+2.5,x/2-2.5])
      translate([xx,0,1.25]) cylinder(h=5,d=2,center=true);
  }
}
module dock_tag_backplate(){
  // The 76 mm provisional hole pitch on an 80 mm panel left just 0.325 mm
  // of plastic outside each 3.35 mm bore. Enlarge the plate instead of
  // silently changing the unmeasured mounting pattern.
  assert(dock_tag_edge_web_mm >= 3 && dock_tag_edge_web_mm <= 8);
  side=max(dock_tag_black_square+20,
           dock_mount_spacing+m3_clearance_d+2*dock_tag_edge_web_mm);
  difference(){
    union(){
      translate([0,0,1.5]) cube([side,side,3],center=true);
      translate([0,-side/2+4,6]) cube([side,8,12],center=true);
    }
    for(x=[-dock_mount_spacing/2,dock_mount_spacing/2],
        y=[-dock_mount_spacing/2,dock_mount_spacing/2])
      // Bore through the 12 mm rear stiffening rib as well as the plate.
      // A 5 mm cut left the rear pair plugged above z=4 mm.
      translate([x,y,6]) cylinder(h=18,d=m3_clearance_d,center=true);
    for(x=[-dock_mount_spacing/4,dock_mount_spacing/4])
      translate([x,-side/2+4,7]) rotate([90,0,0])
        oval_slot(6,m3_clearance_d,12);
  }
}
module wire_clip(){
  difference(){
    cube([16,13,4]);
    for(x=[3,13]) translate([x,6.5,2]) cylinder(h=6,d=2.3,center=true);
    translate([8,6.5,2.5]) cube([6,4,6],center=true);
  }
}
if(part=="head_bridge") head_bridge();
else if(part=="tof_adjustable") tof_adjustable();
else if(part=="oled_bezel") oled_bezel();
else if(part=="speaker_grille") speaker_grille();
else if(part=="fsr_jaw_pocket") fsr_jaw_pocket();
else if(part=="dock_tag_backplate") dock_tag_backplate();
else if(part=="wire_clip") wire_clip();
else assert(false,"Unknown adapter part");
