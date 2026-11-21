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
| Battery and charge/boost enclosure width / length / height | | power_w / l / h |
| TCA9548A and ULN2003 board physical widths | | mux_w, driver_w |
| Generic VL53L0X GY-530 I2C carrier length, width, lens center and 3.3 V pullup verification | | tof_l / w / lens_offset |
| Sensor lens to floor nominal measured standoff | | tof_floor_height |
| Dock track guide clear width | | dock_clear_width |
| Two independent terminal IR emitter carriers, their lateral separation, lens height, aim and optical overlap | | dock_ir_spacing / ir_left_z / ir_right_z / ir_yaw |
| Two independent seat switches, normally closed polarity, mechanical overtravel and wire clearance | | dock_seat_left / dock_seat_right / dock_seat_overtravel |
| AprilTag printed black square size and camera height | | tag_square_mm, tag_center_height |
| Key and candy actual width and thickness | | object_w / h |
| Actual printer minimum wall and hole clearance | | print_wall, clearance_xy |

**The 68 mm battery gauge was undersized and is now corrected as a body-only fit coupon.** The LPHD7430085 protected 1S candidate is listed as 86 mm long plus leads. `docs/cad/remixes/remaining_fit_gauges.scad` now uses `power_l = 86` mm and refuses shorter overrides. This does **not** establish clearance for the leads, protection board, NTC connector, charger, boost or strain relief; the complete power assembly is still unqualified. Do not treat that gauge as an acceptable enclosure for the candidate pack. A selected cell, NTC connector, protection board, DC boost and strain relief must be measured and fitted together before changing final printed geometry. The 1 W speaker was rejected as the final model; an 8 ohm 2 W Challenge CS20-02P110-04-1X is now the exact fixed candidate. The source-proved 20 x 16 x 4.7 mm rectangular fit coupon (docs/cad/remixes/speaker_rect_fit_gauge.scad) renders watertight, but does NOT establish speaker seating, the stated 1cc sealed acoustic enclosure, real amplifier thermals or speech double talk.

Do not fabricate all 15 dimensions to claim print-ready geometry.
