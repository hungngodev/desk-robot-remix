# Shared desk room station: one owned Feather, not five extra controllers

This is one opt-in station for all five pets, never a motor or charger owner.
Firmware: `src/main.cpp`. Mac decoding and opt-in shared context:
`code/laptop/src/desk_robot/room_station.py`,
`code/laptop/src/desk_robot/runtime.py` and
`code/laptop/src/desk_robot/soil_calibration.py`.

## Source-mapped signals

The `feather_nrf52840_room_bench` and `feather_nrf52840_room_full` targets share the **reported owned**
Adafruit Feather nRF52840. Reusing that board and open source Arduino libraries
does **not** require buying any new Adafruit-branded hardware. Check the exact
owned PCB revision and pinned PlatformIO core before wiring.

| Function | Physical Feather connection | Source behavior |
| --- | --- | --- |
| SCD40 | I2C SDA D22/P0.12, SCL D23/P0.11; address 0x62 | Sensirion periodic CO2, humidity, temperature |
| BME688 | Same 3.3 V compatible I2C bus; 0x77 or 0x76 | Upstream BME68x ambient and raw gas resistance, not VOC ppm |
| AMG8833 | Same 3.3 V compatible I2C bus; address 0x69 | Checked 64-pixel thermal register reads; no identity recognition |
| LD2410C | Serial1 RX D1/P0.24 from radar TX, TX D0/P0.25 to radar RX | Upstream LD2410 at 256000 baud, packet freshness bounded |
| Capacitive soil | Analog A0/D14/P0.04 from **3.3V powered** capacitive probe, common ground | Three 12-bit ADC acquisitions, median and noise/rail rejection in the dedicated `room_full` profile; `room_bench` leaves it off |
| Mac | Feather's USB serial at 115200 | Versioned one-line JSON observations, read-only, opt-in |

Source for the Feather numbers:
[Adafruit nRF52 Arduino Feather variant.h](https://github.com/adafruit/Adafruit_nRF52_Arduino/blob/master/variants/feather_nrf52840_express/variant.h)
and [variant.cpp](https://github.com/adafruit/Adafruit_nRF52_Arduino/blob/master/variants/feather_nrf52840_express/variant.cpp).
The nRF52 UART core computes a custom register divisor for 256000 baud, but
that is **not** proof of correct live LD2410 packets on the physical board.

**No direct 5 V logic is permitted on the Feather signal pins.**
The exact LD2410C carrier's supply may differ from its TX/RX logic level.
Verify sensor board pullups, pin orientation, regulator and connector before
connecting any module. Do not confuse I2C with 5 V tolerant wiring.

## Real build and test sequence

1. Use the existing owned Feather alone on USB. Build with
   `uvx --from platformio==6.1.18 pio run -d code/firmware/room_station -e feather_nrf52840_room_bench`.
   Run the committed C++ soil host test and thermal tests first.
2. Check the actual I2C carrier rails/pullups and address scan, then validate
   SCD40, BME688 and AMG8833 one module at a time. Add LD2410C at the
   exact 256000 baud on UART1 after confirming board supply and logic levels.
3. Soil remains **OFF** in the safe default `feather_nrf52840_room_bench`, but the full required profile `feather_nrf52840_room_full` now compiles the actual A0 ADC code with `ROOM_SOIL_FITTED=1`. Select the full build ONLY when the installed probe is fed from the 3.3V rail, its AOUT maximum is under 3.3V across its operating conditions, its ground is common and no 5V output reaches A0.
   Reject saturated and unstable ADC readings; floating A0 can still look
   plausible, so software alone does not prove a connected probe.
4. Measure the **same probe** in physically dry and wet reference media.
   Enter the two actual raw integers, not guessed percentages, into
   `room_station_soil_dry_adc` and `room_station_soil_wet_adc` in the
   existing `code/config/fleet.hardware.example.toml` configuration.
   They must be valid 12-bit readings separated by at least 100 counts.
   Without both entries, the Mac says only `raw ADC`; with both entries
   it computes a clearly labeled **relative** moisture percentage.
5. Set the Mac's `room_station_port` to the real local `/dev/` serial
   device, and opt in separately to room context before sharing the
   observations among pets. The station never grants robot motion,
   charging, medical conclusions or human identification.

**Purchase and safety status: HOLD.** This file gives source-checked signals
and test procedure. It is not a power schematic, a measured PCB revision,
a verified dry/wet calibration, a completed physical station, or an approved
five-pet purchasing order.

The Feather nRF52840 Express [official analog pin reference](https://learn.adafruit.com/introducing-the-adafruit-nrf52840-feather/pinouts) uses a nominal 0 to 3.6 V SAADC measurement span with gain one sixth. **The measurement span is not permission to apply 5V to an I/O pin.** Use a 3.3V powered capacitive probe with a verified 0 to 3.3V analog output and common ground, away from water ingress at the PCB head. Once it is connected, use `feather_nrf52840_room_full` and verify dry/wet calibration. No newly purchased Adafruit board is required.
