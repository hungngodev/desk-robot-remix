# One Robot Fusion mechanical measurement sheet

Fill the actual part dimensions before replacing a parameter in Fusion.
These blank fields are **intentional** and are not permission to guess a fit.

| Interface | Measured mm | Proposed Fusion parameter |
| --- | --- | --- |
| Overall track outside width | | track_outer_width |
| Main stepper motor shaft center spacing | | motor_center_spacing |
| MG90S case length / width / body thickness | | servo_case_l / w / h |
| MG90S horn shaft center and screw boss | | servo_horn_center |
| XIAO Sense assembled board width, height and camera depth | | sense_w / h / depth |
| SSD1306 PCB width, height and window active area | | oled_pcb_w / h, oled_screen_w / h |
| Exact Challenge CS20-02P110-04-1X 20 x 16 x 4.7 mm body, solder pads and gasket dimensions | | speaker_l / speaker_w / speaker_depth / acoustics_1cc |
| Acoustic cup net volume, compressed gasket thickness, sealed lead feedthrough and interference to camera/mic/OLED | | speaker_air_cc / gasket_h / lead_seal / head_clearance |
| WROOM dev board assembled envelope and USB service clearance | | wroom_w / l / usb_clearance |
| Protected 1S pack complete body including PCM and NTC exit width / length / height | | pack_body_w / pack_body_l / pack_body_h |
| Pack connector housing width / length / height, free lead length, wire gauge and minimum safe bend radius | | pack_connector_w / pack_connector_l / pack_connector_h / pack_lead_free_l / pack_lead_awg / pack_lead_bend_r |
| Charger board complete envelope including TS parts, USB or terminal overhang and required insulated clearance | | charger_w / charger_l / charger_h / charger_service_clearance |
| Boost regulator complete envelope including tallest component, connector overhang and thermal clearance | | boost_w / boost_l / boost_h / boost_thermal_clearance |
| Fuse, power switch, strain relief and battery removal/service path envelopes | | fuse_envelope / switch_envelope / power_strain_relief / battery_service_clearance |
| TCA9548A and ULN2003 board physical widths | | mux_w, driver_w |
| Generic VL53L0X GY-530 I2C carrier length, width, lens center and 3.3 V pullup verification | | tof_l / w / lens_offset |
| Sensor lens to floor nominal measured standoff | | tof_floor_height |
| Dock track guide clear width | | dock_clear_width |
| Two independent terminal IR emitter carriers, their lateral separation, lens height, aim and optical overlap | | dock_ir_spacing / ir_left_z / ir_right_z / ir_yaw |
| Exact two independent seat switch bodies, mount pitch / hole diameter, free and operating positions, normally closed polarity, overtravel and wire clearance | | dock_seat_left / dock_seat_right / dock_seat_body / dock_seat_mount_pitch / dock_seat_hole_d / dock_seat_fp / dock_seat_op / dock_seat_overtravel / dock_seat_wire_clearance |
| AprilTag printed black square size and camera height | | tag_square_mm, tag_center_height |
| Key and candy actual width and thickness | | object_w / h |
| Per-pose load-bearing wheel/track/caster/dock-guide contact coordinates in body X forward Y left, measured separately for stowed, extended key, lifted candy, and docked | | poses[].support_contacts_mm |
| Actual mass and 3D center of mass for body and tracks, full protected power stack, head, gripper, sensors/wires, key and candy in four poses | | stability_mass_groups / stability_com_xyz |
| Maximum mounted chassis roll and pitch during loaded approach, and required static perimeter reserve | | stability_roll_max_deg / stability_pitch_max_deg / static_edge_margin_mm |
| Actual printer minimum wall and hole clearance | | print_wall, clearance_xy |

## IMU, eight ranging brackets and cable sweep evidence

The selected installed IMU is the MPU6050 / GY-521. The reported BerryIMU is
a spare; record its envelope separately only if an explicitly approved
alternative mount is being evaluated. Do not mount both by default.

| Interface | Actual measured value | Fusion parameter / evidence |
| --- | --- | --- |
| GY-521 populated PCB, mounting pitch and hole diameters, tallest part, solder/header and connector envelope | | imu_board_mount_envelope |
| GY-521 body-frame axis orientation and retention, mounting surface and minimum surrounding clearance | | imu_axes / imu_mount / imu_min_clearance |
| Optional spare BerryIMU revision and complete envelope, if evaluated separately | | spare_imu_revision / spare_imu_envelope |
| Front VL53L0X PCB/retainer clearance with jaw stowed, extended and lifted | | front_tof_min_clearance_by_pose |
| Rear VL53L0X PCB/retainer clearance to dock guides, backstop, contacts and wires | | rear_tof_min_clearance_by_pose |
| Each downward, front, left, right and rear module: lens center XYZ in body frame, aim, actual connector envelope and unobstructed optical path | | tof_lane_geometry[8] |
| XIAO camera flex and each internal signal cable: part/revision, thickness/width, connector withdrawal envelope, specified static/dynamic bend radius and observed minimum radius | | cable_route_records |
| Each cable route: minimum free clearance to closed shell, screw tips, head bridge, tracks, rack, jaw, brackets and dock through all allowed motion | | cable_min_clearance_by_pose |
| Cable restraints: location, protected edge/exit, service loop, verified strain relief and connector retention | | cable_restraint_records |

Use Fusion Inspect > Interference on the real populated component envelopes
and retain a separate measurement record for each lane and cable. Sweep the
full permitted gripper and drivetrain travel, head removal and dock seating;
a single nominal assembly pose is insufficient. Measure the camera ribbon's
specified bend radius for its exact flex and connector; do not assume the
wire-clip slot is suitable for a camera ribbon or that a tie is strain relief.
Reject pinching, rubbing, hard folds, contact with moving/fastener parts and
any unsupported clearance or bend-radius claim. Record the smallest measured
gap and its pose; do not substitute an arbitrary generic tolerance for a
supplier constraint or measured manufacturing stack-up. Start these trials
unpowered and retain all existing physical safety and release gates.

## Supplier reference envelopes, not measured fit (November 21)

These are verified seller or manufacturer **nominal board dimensions**, not
measurements of the actual shipped PCB, headers, attached leads or installed
lens offsets. The blank `Measured mm` cells above intentionally remain
blank. Use these numbers to prepare reversible CAD fit coupons, then inspect
the physical revision before releasing printed parts.

1. [ElectroPeak GY-530 VL53L0X carrier SEN-19-006](https://electropeak.com/gy-530-vl53l0x-laser-range-finder) is listed as
   **10.5 by 13.3 mm**, with a seller advertised minimum ranging distance of
   **30 mm**. The actual optical center, lens-to-surface standoff, mounting
   angle and pad-side 3.3 V SDA/SCL pullups are still unmeasured. A nominal
   13.5 mm optical mounting height cannot be declared a working floor read
   against a 30 mm published minimum.
2. [ElectroPeak TCA9548A eight channel board COM-05-067](https://electropeak.com/tca9548a-1-to-8-i2c-8-way-multi-channel-expansion-board)
   is listed as **30 by 21 by 2 mm** before header/wire clearance. It advertises
   3.3 V and 5 V compatibility, but the actual breakout pullups must be
   measured on the installed 3.3 V bus. Chip capability alone does not prove
   this specific assembled board safely isolates voltages.
3. [Pololu S13V30F5 #4082](https://www.pololu.com/product/4082) is a
   candidate, not a released converter. Its manufacturer mechanical envelope
   is **22.9 by 22.9 by 9.7 mm** before wiring and thermal air space. Its
   low-cell current, mounting and enclosure fit remain separate power
   qualification gates.

**The 68 mm battery gauge was undersized and is now corrected as a body-only fit coupon.** The LPHD7430085 protected 1S candidate is listed as 86 mm long plus leads. `docs/cad/remixes/remaining_fit_gauges.scad` now uses `power_l = 86` mm and refuses shorter overrides. This does **not** establish clearance for the leads, protection board, NTC connector, charger, boost or strain relief; the complete power assembly is still unqualified. Do not treat that gauge as an acceptable enclosure for the candidate pack. A selected cell, NTC connector, protection board, DC boost and strain relief must be measured and fitted together before changing final printed geometry. The 1 W speaker was rejected as the final model; an 8 ohm 2 W Challenge CS20-02P110-04-1X is now the exact fixed candidate. The source-proved 20 x 16 x 4.7 mm rectangular fit coupon (docs/cad/remixes/speaker_rect_fit_gauge.scad) renders watertight, but does NOT establish speaker seating, the stated 1cc sealed acoustic enclosure, real amplifier thermals or speech double talk.

Do not fabricate any blank measurement to claim print-ready geometry.
