# Haptic coin motor, one source reused electrical path

This is the **one robot bench candidate**, NOT a buy approval or a completed
board-level test. The 3 V coin motor already reported owned should be reused for
the first test. No newly purchased Adafruit hardware. The complete design uses
the existing `MCP23017` on 0x71 channel 5, not another ESP32 or I2C mux.

## Selected source interfaces and allocation

* `code/firmware/body/lib/AccessorySensors/AccessorySensors.cpp` is the
  single owner of the existing 0x71 mux and MCP23017. It writes and verifies
  `OLATB` at BANK=0 register 0x15. `GPB2` is the ONLY haptic output.
  `GPB0` is still the active-low reed input, `GPB1` still the active-high PIR.
  Required `GPIOA` dock contacts and charger status are sampled **first**.
* The expander output **cannot** drive a motor directly. A stalled I2C bus can
  leave the `OLATB` latch HIGH indefinitely. A MOSFET gate pulldown alone does
  **not** fix that fault. Physical timing MUST be independent of ESP32 code.
* The suggested generic timing device is **TI CD74HC123E**, an active PDIP16
  74HC123 dual retriggerable monostable. Its **HC** family is rated for 2 V to
  6 V; use 3.3 V, not the 5 V-only HCT variant. The one-shot use of a generic
  74HC123 comes from the manufacturer's standard application and pinout, not
  an invented sensor library. It is an inexpensive candidate, not a qualified
  exact assembled PCB.
* Use a qualified AO3400-class MOSFET low-side motor stage, flyback diode,
  appropriate small passive components, and a motor supply that meets the
  actual coin motor's marked voltage and measured stall current. Do not route
  motor current through GPIO, MCP23017, breadboard contact or DuPont signal
  wire.

## Proposed one-channel 74HC123 bench netlist

Verify the exact ordered TI package pinout **before building**, and inspect the
footprint orientation. The following is for the standard 16-pin HC123 channel
one pin arrangement, not an unidentified generic module:

| Net | Proposed connection |
| --- | --- |
| 3V3 logic | 74HC123 VCC pin 16, 100 nF local decoupling to GND |
| Ground | Pin 8, common with MCP23017 and MOSFET source |
| Input A | 1A pin 1 held LOW for positive-edge B triggering |
| Edge input B | MCP23017 GPB2 to 1B pin 2 with externally defined LOW at reset, for example a 10 kΩ pulldown |
| Reset | 1CLR pin 3 held HIGH at verified 3.3 V, not floating |
| Haptic pulse Q | Active-HIGH 1Q pin 13 to AO3400 gate through suitably chosen gate resistor; external 100 kΩ gate pulldown to GND |
| Unused inverse Q | Pin 4 no load |
| Pulse RC | Pin 15 REXT/CEXT via 180 kΩ nominal timing resistor to 3V3; 1 µF nominal ceramic capacitor between pin 15 and pin 14 CEXT; pin 14 to ground |
| Channel two (DC only) | Reserved as a CPU heartbeat motor cutoff candidate in [dc-motor-independent-watchdog.md](dc-motor-independent-watchdog.md). Tie channel two inactive in STEP builds; only wire its independent 2B/2Q timer if the DC motor cutoff schematic is accepted. Do not connect it simultaneously to a STEP phase GPIO23 |
| Motor circuit | Motor positive to verified regulated motor supply, motor negative to AO3400 drain, AO3400 source to GND, flyback diode cathode to motor positive and anode to drain |

TI specifies its approximate HC123 relation `t = 0.45 * R * C` **at 5 V**.
The 180 kΩ and 1 µF example would imply about 81 ms **at that specified voltage**, not a proven 81 ms at the proposed 3.3 V logic rail. This is **not a
verified upper bound**: capacitor derating, tolerance, startup, noise and
retrigger behavior must be measured with the actual board. Check that a
continuous GPB2 HIGH and an abruptly disconnected I2C bus cause **one short
physical output pulse followed by LOW**, not a sustained motor drive. Choose
capacitor voltage rating, real capacitance at 3.3 V, and diode protection from
the selected IC's exact datasheet; review unused channel termination too.

## Existing source behavior

`DESK_ROBOT_ENABLE_HAPTIC=1` is available only in
`esp32_full_haptic_lab` and `esp32_dc_integrated_lab`. The normal `esp32_full` and `esp32_dc_full` keep
haptic power **OFF** by default until hardware acceptance.

1. Boot writes zero to MCP23017 `OLATB` before configuring only GPB2 as an
   output and verifies the latch and direction by readback.
2. One genuine, new CAP1188 touch zone transition queues a local request.
   Duplicate, boot baseline, and network speech requests cannot trigger it.
3. The next optional mux lane 5 pass first collects fresh required dock
   contact/status data. A docked, stale or invalid record rejects vibration.
4. At most one positive GPB2 edge is generated after cooldown; the next mux
   lane 5 pass deasserts GPB2. The edge and deassert are each read back.
5. A failed mux transfer or GPIO readback disables haptic requests and
   invalidates cached optional/dock evidence. A later verified lane 5 pass
   attempts to drive OLATB low, but the **physical one-shot** is still required
   because I2C may never recover.

## Acceptance tests, not yet performed on an actual device

Use a current-limited bench supply and disconnected drivetrain/charger power.
Confirm 3.3 V B logic is recognized, no rise while boot/reset, one pulse per
qualified CAP event, minimum 1.5 s between pulses, and no response on docked
or stale GPIOA. Use an oscilloscope to measure GPB2, monostable Q and MOSFET
drain for a stuck-high GPB2, forced bus NACK, SCL held LOW, power-cycle, and
contact change midpulse. Verify independent pulse termination and current/heat
under the actual 3 V coin motor. Repeat after vibration mechanically couples
into the ToF, IMU, camera and microphone mounts.

Source references:

* Microchip MCP23017 official register table:
  https://ww1.microchip.com/downloads/aemDocuments/documents/APID/ProductDocuments/DataSheets/MCP23017-Data-Sheet-DS20001952.pdf
* TI active CD74HC123 and 3.3 V HC logic timing:
  https://www.ti.com/product/CD74HC123
* ST standard 74HC123 pin diagram and monostable example:
  https://www.st.com/resource/en/datasheet/m74hc123.pdf

Do not mark this as a qualified haptic kit or place a fivefold order before a
physical prototype. One kit includes the haptic timer, MOSFET, diode, resistor,
capacitor, connectors and wiring; do **not** add it as a second motor to the
forty-nine primary BOM roles.
