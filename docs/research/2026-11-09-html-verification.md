# ESP32 Deskpet Ideas engineering audit

Audit date: 2026-11-09

Source: user supplied `ESP32 Deskpet Ideas.html`, 1,074,994 bytes, **41 HTML section elements, 44 h2 headings, 316 h3 headings and 231 expandable details blocks**. The active project and topic sections (Power, Drive, Cliff, Touch, Audio, Head, Mac and Proactive) precede the later Xiaozhi-era research library; older instructions must not override the live implementation.

Audited base: `codex/initial-remix`, commit `aa7fb7deebbefda0d1642894165f4398849f360f`.

## Evidence labels

* **SPEC VERIFIED**: a datasheet or official manufacturer reference supports the stated interface or component capability.
* **SOURCE VERIFIED**: the current repository contains the described code, configuration or documented requirement. This does not imply it was run on a device.
* **AUTOMATED TEST**: record a passing CI run, exact commit and named job before using this label for a newly changed version. Skipped tests do not count as passes.
* **BENCH VERIFIED**: the actual owned board, module, wiring, fixture, current and measured output were tested, with original results recorded.
* **BUILD VERIFIED**: one assembled robot passed all mandatory safety, mechanical, voice and pickup gates.
* **FLEET VERIFIED**: every robot independently passed its applicable hardware gates and the complete group passed the conversation and safety tests.

At this checkpoint there is **no BENCH VERIFIED, BUILD VERIFIED or FLEET VERIFIED evidence**. The physical trials CSV has only a header. No shop listing, prior example, simulated test or component datasheet can replace hardware testing.

## Executive verdict

**NOT A VERIFIED BUILD.** The original HTML is a research and proposed implementation design, not an as-built schematic. The repository contains a guarded motor/control foundation, prepared Sense head firmware, laptop coordinator, simulation tests and source CAD, but not integrated calibrated cliff sensor I/O, a qualified battery/power path, actual full duplex echo cancellation or a measured gripper.

The following entries are independently auditable discrepancies between the HTML and actual repo.

| ID | HTML claim or proposal | Verified repo/manufacturer fact | Decision and blocking test |
| --- | --- | --- | --- |
| PIN01 | MAX30102 paw on GPIO41 SDA/GPIO42 SCL | In the Sense board these pins are onboard PDM microphone DATA41/CLOCK42. The repo's body I2C is GPIO21 SDA/22 SCL. See [Seeed pin map](https://wiki.seeedstudio.com/xiao_esp32s3_pin_multiplexing/) | Reject HTML wire assignment. Use the WROOM bus, possibly mux channel 5, only after breakout voltage/pullup check. No battery connection or power-on until validated. |
| INV01 | About five purple GY MAX30102 modules were owned and approved Nov 6 | The current repo inventory and bill do not establish their receipt or count | Add as a **reported but unverified** optional input until board photos/count and electrical IDs exist. Do not change original paid total. |
| SEN01 | Four VL6180X units are locked for five robots | ST now marks [VL6180X obsolete / out of production](https://www.st.com/en/imaging-and-photonics-solutions/vl6180x.html) | Research [VL53L4CD](https://www.st.com/en/imaging-and-photonics-solutions/vl53l4cd.html) as an active short range replacement; no fleet order or automatic substitution. It needs a different driver and real desk tests. |
| SEN02 | A five sensor pipelined scan takes about 40 ms | No body sensor acquisition is implemented or measured; mux adds switching overhead | Unverified target, not a specification met. Measure full scan age with two steppers, display and audio active. |
| SEN03 | Mux channel mapping still open | `docs/hardware/wiring.md` already assigns channel 0 front left, 1 front right, 2 rear left, 3 rear right, 4 forward | Keep mapping; test actual optical orientation and I2C pullups. |
| SAF01 | The robot may reverse in degraded sensor mode | Canonical `CliffGuard` fails closed on missing, invalid, stale or uncalibrated sensor frames. Safety docs forbid blind retreat | Reject degraded reverse and recovery motion. Fault latch and USB rearm after fresh healthy samples; remain disarmed until a new deliberate operator arm. |
| MOT01 | About 700 half steps per second and 1000 steps/s², potentially separate full step turn mode | `StepperDrive.h` limits request to 40% of 400 half steps/s = 160 half steps/s, with 320 half steps/s² acceleration. No dual mode or measured wheel calibration | HTML tuning is research only. Do not claim implemented or raise limits until loaded travel, braking and torque tests. |
| PWR01 | A selected IP5306 variant and 1.85 A peak make a safe portable supply | No specific board, cell, charging/protection circuit or loaded current measurement is recorded | Cannot select boost module from charge current or chip headline. Measure rails, battery input, stalls, WiFi and audio; validate cell and board revisions with safe bench equipment. |
| BUD01 | The $34 power architecture fits the $50 all-in cap | HTML power assumption $34 + reported Sense listing $18.87 = **$52.87**, before floor array, mux, front sensor, audio and other material; possible overlap with HTML's separate shopping list remains unpriced | Prototype cannot be declared purchase ready. Build a unique-line delivered cart with receipt, shipping and tax. If impossible, get owner approval to change scope or cap. |
| AUD01 | RIO GPIO7/8/9 speaker wiring is ready | Active Sense speaker map is BCLK4, LRCK7, DOUT8. OLED is 5/6, UART 2/1, PDM 42/41; current audio codec is `NoAudioCodecSimplexPdm` | Do not mix RIO's board map and active firmware. Implement actual playback reference, paired AEC and audible flush. |
| AUD02 | The HTML's relaxed A2 barge bars are sufficient | `docs/guides/audio-barge-in.md` specifies at least 19/20 audible stops within 500 ms, at least 18/20 correct new intents, 10 min echo-only with zero self interruptions | Preserve stronger canonical acceptance; software cancellation traces alone do not pass an acoustic test. |
| FACE01 | RoboEyes chosen and active | Sense firmware uses stock Xiaozhi OLED face, text and emotion UI | Treat RoboEyes as a license-reviewed proposed port, not current behavior. |
| MAC01 | Pipecat worker, shared MLX Whisper, MQTT, utility scorer, AprilTag navigation and docking all integrated | Existing Mac uses Ollama and Kokoro adapters, local coordinator and simulations. Full live integrations have not been demonstrated | Maintain implementation/pending separation, with real device transport and CPU/GPU contention measurements. |
| GRP01 | Lift/gripper works on real keys/candy | Physical trials CSV has no attempts | Require at least 8/10 keys and 8/10 wrapped candy with lift >=10 mm, hold >=3 s, controlled placement. |

## Pins to wire and pins not to borrow

**WROOM stepper profile:** left ULN2003 IN1–4 = 13,14,25,26; right = 27,32,33,23; lift = 18; grip = 19; body I2C SDA21/SCL22; mux RESET GPIO4 only on breakout variants supporting RESET; UART RX16/TX17; touch GPIO34 input only. Current source: `code/firmware/body/include/BodyPins.h`.

**Sense head:** camera pins fixed by Sense carrier, PDM clock42/data41, OLED SDA5/SCL6, MAX98357A speaker BCLK4/LRCK7/DOUT8, UART TX2/RX1. Current source: `code/firmware/head/sense/config.h` and `sense/README.md`. Do not attach a MAX30102, replacement mic or I2C bus to GPIO41/42 while retaining the microphone. Do not put audio into 5V logic inputs or drive speaker negative to ground. The Seeed Sense SD slot shares pins with the audio allocation and must remain unused.

**MUX and sensors:** WROOM body I2C upstream, default mux `0x70` if A0–A2 grounded, four downward ToFs on channels 0–3, forward VL53L0X on channel 4. All downstream `0x29` in the baseline, but the sensor type and bus pullup/regulator requirements must be checked per real breakout. Texas Instruments [TCA9548A datasheet](https://www.ti.com/lit/ds/symlink/tca9548a.pdf) confirms an 8 channel I2C switch, not automatic device discovery or electrical compatibility for every clone.

**Heartbeat option:** MAX30102's [Analog Devices datasheet](https://www.analog.com/en/products/max30102.html) describes separate logic/LED rails. Common purple breakouts differ in regulation and level conversion. Do not presume a labeled `VIN` pin means directly 5V safe, and do not presume a 1.8V logic input accepts 3.3V. Identify the exact board before selection.

## Change control and acceptance

1. Resolve true inventory and delivered prices. Count owned MG90S, stepper driver sets, battery components and MAX30102; confirm purchased Sense revision with readable marks. Keep price unknown where not quoted.
2. Run automated Mac/head host tests and native body tests at a fixed commit. Attempt both WROOM firmware builds; log failures honestly. Head ESP-IDF firmware needs restored upstream, pinned tools and a build job before it is called independently rebuilt. CI is software evidence, not physical safety proof.
3. Print measured servo pocket and a sensor stand. Use a current limited isolated bench supply and catch stand with mechanically supported payloads. Obtain meters, logic analyzer or suitable timing capture, thermal observations and photos.
4. Integrate fail closed sensor sampling, per surface calibration, timestamps, mux status, faults and latency. Never bypass the local guard so the first drive can move.
5. Implement real acoustic echo cancellation and stop/flush propagation and test the canonical barge requirements at defined volume and distance.
6. Record actual load and stop measurements, grip trials and operator supervised surface tests in `docs/records/physical-trials.csv` using the repo's trial schema. Do not insert invented pass rows.
7. Repeat acceptance on each duplicated core and test group one speaker/floor authority before fleet verification.

Until those proofs exist, report **RESEARCHED: yes** for grounded datasheet choices, **SOURCE VERIFIED: yes** for inspected current code and documented rules, **BUILD VERIFIED: no**. Retain all raw test logs and commit identifiers with any future verified claim.

## Manufacturer sources consulted

* [ST VL6180X product status](https://www.st.com/en/imaging-and-photonics-solutions/vl6180x.html)
* [ST VL53L4CD product](https://www.st.com/en/imaging-and-photonics-solutions/vl53l4cd.html)
* [Seeed XIAO ESP32S3 Sense pin multiplexer](https://wiki.seeedstudio.com/xiao_esp32s3_pin_multiplexing/)
* [TI TCA9548A datasheet](https://www.ti.com/lit/ds/symlink/tca9548a.pdf)
* [Analog Devices MAX30102](https://www.analog.com/en/products/max30102.html)
* [Adafruit MAX98357A guide](https://learn.adafruit.com/adafruit-max98357-i2s-class-d-mono-amp/)
* [ST VL53L4CD ULD driver](https://www.st.com/en/embedded-software/stsw-img026.html)

**Caution:** Manufacturer product pages establish component specifications, not the quality, pinout, protection or delivered price of an unidentified marketplace breakout. Actual qualification remains necessary.

## Independent manufacturer status recheck, 2026-11-09

A second current-source check confirmed the key physical conflicts rather than relying only on the earlier HTML audit:

* [ST official VL6180X product status](https://www.st.com/en/imaging-and-photonics-solutions/vl6180x.html): **Obsolete, Out of Production**. Do not silently use the research-era part as a current supply-ready purchase.
* [ST official VL53L4CD product status](https://www.st.com/en/imaging-and-photonics-solutions/vl53l4cd.html): the referenced VL53L4CD part variants are listed **Active, in volume production**. This establishes manufacturer status, **not** breakout availability, complete $50 affordability, compatible physical sensor field geometry or successful firmware migration.
* [Seeed official XIAO ESP32S3 Sense microphone usage](https://wiki.seeedstudio.com/xiao_esp32s3_sense_mic/): **GPIO41 microphone DATA and GPIO42 microphone clock**. The optional MAX30102 cannot occupy those lines while the onboard PDM mic is retained.
* [Seeed XIAO ESP32S3 pin multiplexing](https://wiki.seeedstudio.com/xiao_esp32s3_pin_multiplexing/): GPIO43/44 are standard UART-labelled header pins, but the **actual compiled project's TX2/RX1** allocation is a different deliberate map. Do not rewire the head to a tutorial's 43/44 without corresponding reviewed firmware and collision testing.

This is a manufacturer-document **specification check**. No sample breakout was energized, no near-field ranging trace was captured, no product purchased and no Sense UART/heart pad wiring was bench-tested in this audit.
