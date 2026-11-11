# Read only dock contact and charger status, one complete robot

The hardware plan allocates MCP23017 at WROOM accessory mux 0x71 lane 5, I2C address 0x20. The new firmware adapter uses *only inputs*, with on-chip 3.3V pullups:

* GPA0 and GPA1 are independent normally closed mechanical dock contact confirmation switches. Both should open to HIGH when the robot is seated. A broken wire can look like a pressed switch, so these alone never prove docking or authorize charging.
* GPA2 reads **BQ24074 PGOOD** as an open drain, LOW meaning the charger reports a valid input source. The charger status needs actual powered verification.
* GPA3 reads **BQ24074 CHG** as an open drain, LOW meaning the IC reports an active charge cycle. This is not a current measurement or proof that the battery is accepting charge.

The WROOM reports these four bools through the existing read only `aux` path. The Sense bridge and Mac validator type-check them, reject fictional `charging_verified=true`, and never enable the charger or drive actuators.

Power path proposal for review, **not verified electronics**: a protected compatible 1S cell with pack protection and temperature monitoring, a current and thermally qualified boost converter for the 5V body/head motors, a separately selected single-cell power-path charger operating from a short protected dock input, and correctly fused keyed recessed contacts. A BQ24074 is a useful *reference design* with dynamic power-path management, but has max 1.5A charge current and must not be mistaken for a 5V high current boost output or protection of arbitrary bare 18650 cells. Vendor data: https://www.ti.com/product/BQ24074.

The actual battery, boost, charger board, NTC wiring, input charge contact current limit, thermal load, chassis geometry, shore power, and exposed contact safety remain unselected and cannot be called verified until built and measured. Do not energize exposed metal contacts from this file.
