# Source-first crosscheck against real working robot builds

Purpose: use specific documented and observable open-source implementation,
not imagined drop-in compatibility, to reach a small-volume manufacturing
design that needs measured tolerance calibration rather than component swaps.
The prototypes below cannot establish that combining their parts works; each
adopted interface has an explicit paper and real hardware boundary.

## Independently inspected upstream source and scope

| Reference | Documented physical functionality | License checked | Reuse into this robot | What must not be inferred |
| --- | --- | --- | --- | --- |
| [cgro00/desk-robot](https://github.com/cgro00/desk-robot), [hardware and wiring](https://github.com/cgro00/desk-robot/blob/main/docs/wiring.md) | V1 released with XIAO ESP32S3 Sense camera/PDM mic, MAX98357A, SG90 servos and actual demo; current V2 docs propose MG90S servos, redesigned printed head and 470uF/diode power wiring, but V2 is marked in progress | **MIT** | Use its external 5V to XIAO series Schottky 1N5817 and local 470uF 5V servo bulk approach; exact Seeed VBUS pin rule is independently documented by manufacturer | cgro design has two servos, not two loaded drive motors or charging contacts. Its 5V 2A recommendation is not a qualified rail for our system. Its larger OLED and Dayton speaker are **not** our exact fixed display and Challenge speaker |
| [Seeed XIAO ESP32S3 official power instructions](https://wiki.seeedstudio.com/xiao_esp32s3_getting_started/) | Manufacturer pin rating and proper external 5V feed | Official reference | XIAO 5V external source must connect through diode **anode at supply, cathode at 5V pin**, preventing backfeed to motor rail during USB flashing; 3V3 regulator cited at 700mA, not an actuator supply | 700mA output rating is not proof total PDM, camera, ESP32 WiFi, OLED thermal margin or external 3.3V sensor budget |
| [78/xiaozhi-esp32 audio](https://github.com/78/xiaozhi-esp32/tree/main/main/audio) | Full-duplex voice tasks, Opus AFE and wake barge-in source | Follow pinned upstream commit's license | Existing `sense_reference_codec.cc` overrides Xiaozhi's proven PDM and I2S codec, providing MIC+REFERENCE to the AFE, preserves upstream output `NoAudioCodec::Write` | Actual 90ms default reference delay, loudspeaker echo, acoustic coupling and cancellation under loud playback have not been verified; **this is not a proven barge-in result** |
| [hudrucan/xiaozhi-desk-robot](https://github.com/hudrucan/xiaozhi-desk-robot) | Single documented ESP32S3 visual Xiaozhi rover with N20, ToF source and interactive dashboard | **MIT** | Compare lifecycle, native ESP-IDF camera/audio control and source reuse to our Mac plus head and WROOM separation | Different ESP32S3 board, mechanical scale, camera carrier and power circuit. Never copy pin numbers or assume guaranteed docking |
| [makerspet/makerspet_snoopy](https://github.com/makerspet/makerspet_snoopy) | Physically printable tracked/mobile pet robot CAD and source; 5 optional cliff sensors, actual assembly media | **Apache 2.0** | Source for independent cliff placement and mechanical envelope tests, assembly build and ROS2 sensor lessons | Approximately 300mm base is NOT the small existing desk footprint; no direct bolting of the original mounts, charger or battery |
| [cancast/Desktop-Robot-Arm](https://github.com/cancast/Desktop-Robot-Arm) | Actual printable 3MF/STL, powered 4-SG90 articulated arm and gripper with code and prototype photograph | **MIT** | Proven mechanical joint and gripper reference, stop before end stops, print independent mechanical clearance fit coupons | Actual robot has MG90S, only two servos, different torque geometry and FSR. Do NOT substitute their arm STL as a complete tested gripper without fit/force calculations |
| Original [SMARS](../cad/originals/smars/README.md) fork and Bluino gripper in existing CAD scaffold | Original chassis, lift, head, rack/pinion saved in this repository | **Mixed**; SMARS forklift CC BY NC SA 4.0, Bluino gripper CC BY 4.0, Sparky CC BY SA | May stage original models for *noncommercial bench research only*. Attribution and any sharealike must remain attached | The NC license does **not** authorize commercial production, and saved STL meshes are not assembled fitted joints. This conflict needs a licensed proven commercial alternative before release |

## Source integration invariants to preserve

1. **One WROOM bus owner**: core 0x70 eight VL53L0X, secondary 0x71 multiplexed interactions, one upstream I2C; never assume a second independent bus or use 5V I2C pullups. Existing `TofBus`, `AccessorySensors`, `CliffGuard` are source paths; real bus scope/timing is still unmeasured.
2. **Physical motion cutoff separate from software**: `MotorHeartbeat` on DC only GPIO23 to external CD74HC123 channel 2 and qualified DRV8833 nSLEEP gate. Motor LEDC can keep oscillating during CPU freeze. Stepper variant uses GPIO23 for ULN2003, so never produce one combined harness.
3. **Two 5V motor/servo and audio branches plus diode isolated XIAO head**: diode goes to XIAO only, not the separate MG90S/DRV8833 rail. MAX98357A needs manufacturer specified 0.1uF plus 10uF local supply bypass and appropriately wide speaker/ground runs. 470uF at servo/motor source is a known working starting point, not proof of our simultaneous stall current.
4. **Voice interruption is not merely having a model**: preserve Xiaozhi's AFE microphone and playback reference path, the atomic playback cancellation, mic task priority and audio frames while speaking. Full physical double-talk with camera and WiFi is required, because speakers in small enclosures can overwhelm the PDM microphone.
5. **Physical fit cannot be inherited from a photograph**: verify the exact selected 20x16 speaker baffle, MG90S horn sweep, 8 GY530 lens center and desk stopping distance, protected wired 1S battery, dock contact recess and frame/tag alignment as a single 3D assembly. Make clear of collisions and lead bend radius before any fivefold kit.
6. **Release only actual devices**: no selected DC/STEP mixed motors, no duplicate MAX17048 if integrated BQ27441 power path, no Adafruit branded new boards, no seller board substituted on chip name alone. Every battery and breakout needs current rating, I2C logic, connector keying and actual licensed CAD.

## Required engineering method before declaring buy/print/assemble complete

Use the exact upstream tagged source and author license, exact purchased
supplier PCB revision, one unified electrical schematic, single fitted
Fusion 360/STEP assembly, and reproducible firmware/linker builds.
Apply worst-case electrical arithmetic (minimum cell voltage, combined motor
stall and servo current, hot boost efficiency, load sharing and charger
thermistor circuit), bus address/rise-time and task-latency budgets, tolerance
stack analysis, and failure mode testing for current/reboot/brownout/desk-edge
loss. An independent reviewer should review those artifacts before the first
prototype. Physical tests should then be mostly verification against
**explicit numerical bounds**, not open-ended component shopping.

The exact source contracts cannot prove the unmeasured physical quantities.
In particular do not assign a 3.3V/5V Schottky current rating, use 2A supply
from a smaller robot, or call a watchdog hardware time limit at 3.3V based
on a 5V formula. Those are safety-relevant assumptions, not marginal
printer or sensor calibration.
