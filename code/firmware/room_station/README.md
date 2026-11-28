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
| AMG8833 (optional, not selected for default checkout) | Same 3.3 V compatible I2C bus; address 0x69 | Checked 64-pixel thermal register reads; no identity recognition |
| LD2410C | Serial1 RX D1/P0.24 from radar TX, TX D0/P0.25 to radar RX; common GND; VCC from a separately verified 5 V station branch, **never** the Feather 3V pin | Upstream LD2410 at 256000 baud, packet freshness bounded |
| Capacitive soil (SEN0193) | Analog A0/D14/P0.04 from **3.3V powered** capacitive probe, common ground | Three 12-bit ADC acquisitions, median and noise/rail rejection in the dedicated `room_full` profile; `room_bench` leaves it off |
| Mac | Feather's USB serial at 115200 | Versioned one-line JSON observations, read-only, opt-in |

Source for the Feather numbers:
[Adafruit nRF52 Arduino Feather variant.h](https://github.com/adafruit/Adafruit_nRF52_Arduino/blob/master/variants/feather_nrf52840_express/variant.h)
and [variant.cpp](https://github.com/adafruit/Adafruit_nRF52_Arduino/blob/master/variants/feather_nrf52840_express/variant.cpp).
Qwiic and STEMMA QT are connector options on the same 100 kHz `Wire` bus,
not separate buses. Use only 3.3 V power and logic for this mixed bus, with
common ground. Check the exact carrier pin order and pullups to 3.3 V;
the Feather Express has no default I2C pullups. Parallel breakout pullups
must be assessed together, not blindly duplicated. Check effective pullup
resistance and rise time with all fitted carriers before release. Do not
assume the owned Feather has a native JST-SH connector: use a verified
header-to-JST-SH harness if needed. See the
[Feather pinout](https://learn.adafruit.com/introducing-the-adafruit-nrf52840-feather/pinouts)
and [Qwiic compatibility](https://learn.adafruit.com/introducing-adafruit-stemma-qt/sparkfun-qwiic).

The nRF52 UART core computes a custom register divisor for 256000 baud, but
that is **not** proof of correct live LD2410 packets on the physical board.

**No direct 5 V logic is permitted on the Feather signal pins.**
The pinned [ncmreynolds LD2410 v0.2.2](https://github.com/ncmreynolds/ld2410/tree/v0.2.2)
documents the module supply and 3.3 V UART I/O. Hi-Link's
[LD2410C product reference](https://www.hlktech.net/index.php?id=65)
specifies 5 V supply and 3.3 V serial output; do not infer a higher allowed
supply voltage for the exact fitted carrier.
The owned Feather's official pinout documents its USB power pin as only
nominally 4.5 to 5.2 V, so that pin is a **candidate source, not a qualified
5 V rail**. Do not connect LD2410C VCC to Feather 3V and do not assume the
USB pin meets the exact carrier's minimum voltage/current under cable and
board drop. Before fitting the radar, inspect its exact carrier marking and
datasheet, power it from the station's separately verified 5 V branch with
common ground, and measure the voltage at the radar while streaming. Keep
the station wiring and purchase on HOLD if the measured minimum falls below
the carrier rating. TX/RX remain 3.3 V logic only.
Verify sensor board pullups, pin orientation, regulator and connector before
connecting any module. Do not confuse I2C with 5 V tolerant wiring.

## Station power budget is a qualification gate

The machine-readable plan now records source reference current bounds for every
powered station role. These are screening values, not permission to wire an
unknown breakout. At 3.3 V, the SCD40 datasheet allows up to **205 mA peak**
and 18 mA average in periodic measurement. Bosch lists the BME688 at up to
**12 mA** for customized pressure, humidity, temperature and gas operation.
The optional AMG8833 reference is about **4.5 mA typical**. LD2410C is on the
separate 5 V branch and its protocol documentation requires supply capacity
**greater than 200 mA**, with about 79 mA reference average current.

The owned Feather documentation rates its 3.3 V regulator at **500 mA peak**
but explicitly warns that 500 mA is **not a continuous 3.3 V budget from a
5 V input** because regulator heating matters. Therefore do not approve the
station by adding typical or average sensor currents. Exact carrier regulators,
indicator LEDs, pullups, the soil probe and the Feather itself add load that is
not represented by the bare sensor numbers.

Before station purchase release or enclosure freeze, run the exact fitted
carriers together: SCD40 periodic conversion, BME688 gas heater activity,
AMG8833 streaming (only if the optional carrier is fitted), LD2410C streaming
and the fitted soil probe. Measure the
minimum 3.3 V at the farthest I2C carrier, minimum 5 V at the radar, USB input
current, cable drop and regulator temperature while watching for resets, I2C
errors and USB serial interruption. Keep the room station on HOLD until those
measurements have margin against the exact carrier ratings.

Primary references: Sensirion SCD40/SCD41 datasheet, Bosch BME688 datasheet,
Panasonic AMG8833 product data, ncmreynolds LD2410 v0.2.2 protocol notes, and
the official Feather nRF52840 power management guide. The same URLs are stored
under `room_pod.power_reference.references` in the canonical hardware plan.

## Fault recovery and temporal provenance

The station gives each read-only I2C module independent retry backoff of 5, 10,
20, 40, then at most 60 seconds after repeated failures. Only a complete valid
conversion resets that sensor's retry history; an acknowledged probe alone does
not. Startup and the first fault after successful sampling can probe immediately.
It performs at most one peripheral probe per loop pass so healthy UART radar
and USB telemetry continue running. SCD40 reinitialization sends the documented 0x3F86 stop command through a
bounded Wire transfer, then starts periodic measurement after the required
500 ms settle interval without a blocking sleep. The pinned Sensirion
v1.1.0 stopPeriodicMeasurement() method contains delay(500), so only that
stop command is issued directly; periodic start and readings still use the
pinned library. Previously cached CO2, BME gas values, and thermal
pixels stay invalid until new successful conversions. This is a software
recovery contract and **not** a physical hot-unplug or supply integrity pass.
Bench test all fitted carrier revisions, bus pullups and actual reconnect time.


The pinned nRF52 Wire implementation can still wait indefinitely for a
hardware event: staged sensor scheduling is not a transaction timeout.
Both station profiles therefore start the nRF52840 hardware watchdog before
initializing Wire and feed its sole reload channel only after a complete
main-loop pass. The nominal timeout is four seconds, including CPU sleep
and debugger halt. An incompatible inherited watchdog configuration leaves
the station silent instead of silently operating unguarded. Startup no
longer waits for a USB host. A persistent bus fault may cause repeated
resets; this does not guarantee healthy sensor service while the bus is
stuck. Verify the actual reset reason, USB reconnect/nonce freshness, and
recovery with the exact Feather bootloader and a controlled bus-stall trial.
This is a station availability watchdog, not the WROOM motor watchdog,
a charge grant or physical safety qualification.
Reference: [Nordic nRF52840 WDT product specification](https://docs.nordicsemi.com/r/bundle/ps_nrf52840/page/wdt.html).

## Nonblocking shared radar and BME688 sampling

The pinned Adafruit BME680 2.0.5 source uses `beginReading()` and
`remainingReadingMillis()` to avoid holding the Feather loop during its
150 ms gas-heater cycle. The firmware calls `endReading()` only after the
conversion reports completion; the LD2410C UART remains polled independently.
The USB frame timestamps the last successfully collected BME tuple at its
conservative acquisition start, not its potentially delayed collection time.
The firmware rejects a conversion collected more than 3 seconds after its
start, and the Mac independently rejects a sample older than 3 seconds. The source regression checks
this producer contract but does not prove actual UART packet loss, gas warmup,
electrical fit, thermal accuracy or a physical station trial. Upstream:
https://github.com/adafruit/Adafruit_BME680/tree/2.0.5

## USB reconnect freshness handshake

The Mac sends a fresh random `\nSYNC <16 lowercase hex>\n` challenge
after opening the serial port and again before each accepted report. The
leading newline clears an unfinished request left by an interrupted USB
write without requiring the independently powered Feather to reboot. If
it completes an old nonce, the resulting old ACK is discarded by the Mac.
The Feather replies with `SYNC_ACK <nonce>\n` (CRLF is also accepted). Complete JSON frames received
before the current challenge ACK are discarded even if their fields appear
valid. If the report is delayed more than 2.5 seconds after its ACK, the
Mac discards the late frame and starts a new challenge. If the ACK itself
does not arrive within three seconds, the station remains unavailable.
This prevents old USB frames buffered on reconnect or after a read stall
from masquerading as freshly captured room context. Actual sensor-age checks
remain independently enforced. The challenge is **not** cryptographic
authentication, physical source calibration, or verified room sensor timing.
The standalone bench collector uses the same handshake. Old station firmware
must be rebuilt before current Mac USB context can be enabled.

## Reproducible USB stream evidence capture

After checking the actual Feather PCB and safe sensor voltage domains, run
the read-only collector from the `code` directory against the physically
connected USB port. It uses the same serial line, sensor value and replay
decoder as the Mac, opens one device epoch, and never sends a motor or charger
command.

The running Mac runtime and this standalone collector both acquire the same
pySerial exclusive port lock. Before the bench capture, safely stop the
Mac runtime and wait for its room USB reader to close; do not run a serial
monitor on that port at the same time. A port-in-use failure is not a reason
to open a second station or bypass the lock. After the collector exits,
restart the normal Mac runtime against the same verified Feather port.
For the fleet trial, verify the same fresh shared observation in each of
the five pets' consented contexts, not five concurrent serial readers.

```bash
cd code
umask 077
ROOM_TRIAL_DIR="$HOME/.desk-robot/room-trials"
mkdir -p "$ROOM_TRIAL_DIR"
chmod 700 "$ROOM_TRIAL_DIR"
uv run --no-sync python scripts/bench_room_station.py \
  --port /dev/cu.YOUR_REAL_FEATHER_PORT --seconds 60 \
  --report "$ROOM_TRIAL_DIR/room-usb-$(date -u +%Y%m%dT%H%M%SZ).json"
```

Keep trial reports in this private directory, **outside the Git checkout**.
The collector requires the final report directory to have mode 0700 and
creates a new report with mode 0600. It refuses an existing filename rather
than overwriting evidence. The repository's tracked `docs/records/reports`
folder is not a private capture destination and must not receive raw trial
receipts. Use a new filename for each attempt.
Invalid CLI arguments exit with status 2 before creating report directories.
A failed capture retains its private diagnostic receipt and exits with status 1.
A 3600-second request also requires the one-hour USB continuity screen to pass
for exit status 0. Neither exit status 0 nor a continuity pass qualifies hardware.

Record the actual operator, board revision, connected exact sensor carrier
revisions and independent voltage/current/temperature instrument readings
separately. The JSON intentionally contains **only aggregate counts and
Mac receive timing**, not a raw radar presence, room CO2 or thermal history.
A recorded USB frame is not physical authentication of the station, sensor
accuracy, 3.3 V or 5 V rail qualification, actual charging or motion authority.
The report explicitly keeps those physical flags `false`.

## Real build and test sequence

1. Use the existing owned Feather alone on USB (confirm the exact local `/dev/`
   port and DFU/UF2 bootloader readiness; keep EXP-033 bootloader HOLD intact and
   do **not** assume OTA rollback or PCB revision). Build with
   `uvx --from platformio==6.1.18 pio run -d code/firmware/room_station -e feather_nrf52840_room_bench`.
   Run the committed C++ soil host test and thermal tests first, then flash the
   bench profile to the verified board with
   `uvx --from platformio==6.1.18 pio run -d code/firmware/room_station -e feather_nrf52840_room_bench -t upload --upload-port <CONFIRMED_PORT>`
   (STOP immediately on upload/bootloader error). Observe post-boot firmware
   banner and USB CDC enumeration before any sensor reads.
2. Check the actual I2C carrier rails/pullups and address scan, then validate
   SCD40 and BME688 one module at a time. For a fitted, consented optional
   AMG8833 use the explicit bench thermal profile described below. Add LD2410C at the
   exact 256000 baud on UART1 after confirming board supply and logic levels.
3. Soil remains **OFF** in the safe default `feather_nrf52840_room_bench`, but the full required profile `feather_nrf52840_room_full` now compiles the actual A0 ADC code with `ROOM_SOIL_FITTED=1`. Select the full build ONLY when the installed probe is fed from the 3.3V rail, its AOUT maximum is under 3.3V across its operating conditions, its ground is common and no 5V output reaches A0, and explicitly reflash it with `uvx --from platformio==6.1.18 pio run -d code/firmware/room_station -e feather_nrf52840_room_full -t upload --upload-port <CONFIRMED_PORT>` after stopping on any failed port/upload check.
   Reject saturated and unstable ADC readings; floating A0 can still look
   plausible, so software alone does not prove a connected probe.
4. Measure the **same probe** in physically dry and wet reference media.
   Enter the two actual raw integers, not guessed percentages, into
   `room_station_soil_dry_adc` and `room_station_soil_wet_adc` in the
   existing `code/config/fleet.hardware.example.toml` configuration.
   For the selected SEN0193, both readings must be 1..4094 and dry ADC
   must exceed wet ADC by at least 100 counts. Reversed endpoints are rejected.
   See the [manufacturer example](https://wiki.dfrobot.com/sen0193/docs/18036)
   for the decreasing ADC response with moisture; measure the actual fitted probe.
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

## AMG8833 source bounds and failure behavior

The optional thermal array is disabled in both standard bench and full builds
(`ROOM_AMG_FITTED=0`); a connected array is not probed, recovered or sampled,
and its JSON field remains `valid:false`. Soil selection is independent.
Only with explicit operator consent and a verified fitted carrier, select
`feather_nrf52840_room_bench_thermal` (soil off) or
`feather_nrf52840_room_full_thermal` (soil on). These opt-in builds enable
acquisition at the Feather, independent of Mac context-sharing settings.
They do not implement live consent revocation: to stop acquisition, disconnect
station power immediately and reflash a standard disabled profile before
resuming. Mac-side filtering alone does not stop the Feather's I2C reads.
No physical qualification or purchase release is implied.

The selected **AMG8833 high gain** part has a Panasonic-specified **0 to 80 °C measured-object range**, distinct from the AMG8834 low gain -20 to 100 °C variant. The portable `thermal_pixels.h` checks signed two's-complement 0.25 °C pixel values against the selected part's limits. A malformed transfer or any out-of-range pixel rejects that frame; a rejected 16-byte chunk does not partially overwrite the previous chunk. These limits are a conservative validity screen, not a claim of ±0 °C accuracy, successful electrical integration, or physical body-temperature detection. Source: https://industry.panasonic.eu/products/components/sensors/ir-thermophile-array-sensor-grid-eye .

The exact host files `thermal_pixels.h` (blob `b1c38da57be7db1956d4dafe21d7ed9860433fa8`) and `thermal_pixels_tests.cpp` (blob `ccd0f47ae6060ad03bb6e1406a75a7be8b29a5f1`) passed a local standalone `g++ -std=c++17 -Wall -Wextra -Werror -fsanitize=address,undefined -fno-omit-frame-pointer -O1` test on November 17, 2026. The complete Feather PlatformIO build and a real AMG8833 bus trial are **NOT EXECUTED**. Keep the room station and fleet procurement on HOLD pending physical validation.


## C++11 compatible optional soil ADC source

The pinned Feather nRF52840 Arduino core compiles the optional `ROOM_SOIL_FITTED=1` source under an older C++ language mode. `soil_sample.h` uses explicit member assignment to construct accepted `SoilSample` values. The exact committed header and fake ADC test were independently compiled and executed with C++11, C++14, and C++17 with address/undefined behavior sanitizers; verification details and blob hashes are in `docs/records/verification.md`. The November 17 room full PlatformIO job initially failed compilation due to C++11 aggregate rules, and the subsequent complete PlatformIO rebuild was not yet observed. The source filter cannot establish real probe calibration, analog 3.3 V input safety, soil moisture percent, or electrical suitability.
