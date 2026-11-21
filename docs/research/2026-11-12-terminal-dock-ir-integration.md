# Terminal dock IR: independent research and integration gate (2026-11-12)

## Evidence checked
PR #17 and its `docs/hardware/full-feature-wiring-and-shopping.md` reserve WROOM GPIO36/39 for independent demodulated 38 kHz receivers. The branch documentation states that bounded RMT/NEC burst decoding has been implemented in source, but receiver polarity, optical timing, bearing calibration, and powered contact docking have not been physically qualified. This is not evidence of reliable autonomous docking.

## Reuse candidates and fit
1. **Espressif ESP-IDF RMT receiver and NEC examples**: https://github.com/espressif/esp-idf/tree/v4.4/examples/peripherals/rmt . Prefer the official peripheral and timing approach already used by the WROOM source. Check the pinned ESP-IDF revision and example license before copying code; no example code is copied by this note. RMT can timestamp demodulated pulses without a polling loop, but cannot by itself establish bearing or safe charger alignment.
2. **Arduino-IRremote**: https://github.com/Arduino-IRremote/Arduino-IRremote . Mature decoder reference for pulse tolerances and noise handling, but a second runtime decoder would duplicate the existing RMT implementation and could interfere with timing critical cliff sensing. Evaluate its current license and target support at the pinned revision before adoption. Design reference only.
3. **IRremoteESP8266**: https://github.com/crankyoldgit/IRremoteESP8266 . ESP32-capable protocol decoding reference; potentially larger than the narrowly required terminal receiver. Do not transplant its runtime until license, version and resource budget are checked. Design reference only.

## Smallest useful next iteration
Inspect the actual WROOM RMT decoder and tests on PR #17 before writing any replacement. Add a deterministic source test that feeds each independent channel: valid complete bursts, truncated bursts, repeated frames, noise, simultaneous left/right reception, stale timestamps and a channel stuck active. Verify that none of these cases grants a motor permit or energizes charging. The expected output is *read-only dock evidence*, with age and channel provenance.

## Physical acceptance gate
Before any automatic terminal approach, select and document actual 38 kHz receiver parts and dock transmitter geometry; measure electrical idle polarity and supply compatibility, pulse widths and demodulator recovery, left/right separation at multiple angles and distances, ambient light susceptibility, and signal loss. Then measure contact seating with both independent normally closed switches and actual charger PGOOD under load. Keep all motion disarmed on stale or contradictory evidence. Never equate decoded NEC data with a verified bearing, successful docking or safe charging.

## Coordination
Existing PR #17 remains the only integration PR. This note is a research and test plan, not a driver import, passing test, or physical certification. Implementation and QA should reuse the existing RMT path unless a concrete failing test proves replacement necessary. Charging and printable mechanical acceptance remain separate blockers.
