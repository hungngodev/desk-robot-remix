# 1S rail regulator qualification: avoid a nominal 5 V false pass

Research checkpoint, November 13, 2026. This is a selection constraint for the complete WROOM + XIAO + two 28BYJ-48 + two MG90S robot, not a wiring authorization, selected charger, bench result, or reduction of hardware scope.

## Manufacturer evidence and reuse

* Pololu S7V8F5, product 2123: https://www.pololu.com/product/2123/1461 . Fixed 5 V, VIN 2.7–11.8 V, advertised typical 500 mA to 1 A depending on VIN and load. At 1S voltage it is BOOSTING, so the 1 A step-down headline is not a safe design budget. Pololu explicitly says the sustainable current is below the thermal-shutdown graph and recommends no more than about 1 A throughout the input range. The board has no reverse-polarity protection. **Do not silently approve this regulator for the entire robot.**
* Pololu S7V7F5, product 2119: https://www.pololu.com/product/2119/ . Approximately 500 mA continuous in boost operation; likewise not a qualified full-robot supply. Both products are useful reference designs/specifications, not imported firmware or proof of sufficient capacity.
* Adafruit BQ24074 published Eagle schematic and board layout: https://github.com/adafruit/Adafruit-BQ24074-PCB . Hardware license is Creative Commons Attribution ShareAlike with attribution requirements; a published power-path schematic can inform the comparison, but is **not** a verified autonomous contact charger, battery protection circuit, or permission to copy the board into the robot without design and license review. No source copied.

## Actual system-level acceptance

1. Measure simultaneous peak and continuous 5 V rail load with BOTH steppers stepping, both servos loaded, XIAO transmitting audio/camera, WROOM WiFi active, and worst-case startup/brownout. Include cell voltage near the protected pack's discharge cutoff and connector/harness drop. Record rail minimum, ripple, current, regulator temperature, and recovery behavior; nominal board ratings are not measurements.
2. Separate battery protection, charge management, input power-path control, 5 V regulation and motor power isolation in the electrical schematic. A charger IC alone is not battery protection; a regulator alone is not charge control. Require exact purchased pack and PCB revisions, matched cell specifications, rated wiring, fusing and thermal evidence.
3. Keep charging contacts unpowered or electrically isolated until independent polarity, reverse-current, short, contact bounce, partial contact, wet/foreign-object and dock-unplug tests have passed. Dock presence, AprilTag and two IR observations are not proof of charge current.
4. Preserve WROOM fail-closed motor stop and no automatic resume on undervoltage, reset, lost I2C, dock contact, or sensor invalidation. Charging must not be enabled by a Mac model/tool result.

## Decision and next owner action

**Blocked:** neither Pololu module above is approved as the final 5 V rail and no charger topology is selected by this note. Power/physical QA owner should extract the exact simultaneous load budget from the current BOM and selected parts' datasheets, identify a manufacturer-supported protected 1S charger/power-path and regulator with documented low-cell continuous and transient margin, then test a current-limited bench supply before a cell or dock contact is connected. Record board revision, schematic, measurements and regression evidence in docs/records/verification.md. Preserve the existing charging inhibit and full feature set.

## November 13 charger power path comparison: output is not a 5 V rail

Manufacturer references checked:

* TI BQ24074: https://www.ti.com/product/BQ24074 . Its regulated OUT is nominally 4.4 V, not a regulated 5 V motor/head rail. The published 1.5 A maximum is a programmable charging/input class rating, not demonstrated continuous five volt load capacity. DPPM reduces battery charge current when the input source is constrained; battery supplementation can occur. Its thermistor, power good and charge status do not independently verify dock contact polarity, cell protection or rail integrity. The existing Adafruit BQ24074 PCB is a CC BY SA reference, not an approved dock design.
* Microchip MCP73871: https://www.microchip.com/en-us/product/mcp73871 . A production 1S linear charger with integrated load sharing, programmable charge current up to 1 A and total input current control up to 1.8 A. It is not a regulated 5 V boost converter or substitute for pack protection. Manufacturer documentation does not prove that its breakout, dock contacts, cable or thermals tolerate this robot's simultaneous motor and audio peaks. Hardware schematic reuse requires a separate board specific license check; no PCB or source copied.

**Cross module integration constraint:** Never connect either charger's system output to the nominal 5 V ULN2003/servo/head rail as if it were regulated to 5 V. Keep the 1S cell, independent pack protection, load sharing charger, qualified 5 V boost rail and 3.3 V sensor supply as distinct schematic blocks. During docking, test worst case system load plus charging current against adapter input limits, charge throttling, battery supplementation, connector drop and thermal shutdown. PGOOD indicates input presence, not proof of net battery charging; acceptance requires independent voltage/current measurement and safe partial contact and unplug behavior. Existing WROOM motor inhibit and no automatic rearm remain mandatory.

**Disposition:** BQ24074 and MCP73871 are candidate manufacturer reference architectures, not selected or qualified parts. Next power owner action is a rail load worksheet from exact selected part revisions, followed by current limited bench validation and only then a battery/dock schematic decision. No firmware change or physical qualification is implied.
