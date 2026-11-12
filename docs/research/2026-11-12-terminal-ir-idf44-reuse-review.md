# 2026 11 12 terminal IR reuse review

## Scope and current source truth
PR #17 hardware plan reserves ESP32 WROOM GPIO36 and GPIO39 for independent demodulated 38 kHz dock IR receivers. The plan says ESP IDF 4.4 RMT decoding is present, but receiver polarity, optical timing, bearing calibration and physical terminal docking remain unqualified. This note does not authorize motion or charging.

## Upstream comparison
1. Espressif ESP IDF legacy RMT NEC TX/RX example, matching the project's ESP IDF 4.4 driver generation. Primary reuse/reference: https://github.com/espressif/esp-idf/tree/release/v4.4/examples/peripherals/rmt_nec_tx_rx . Confirm the exact file header and license on the pinned revision before copying code. Older example uses ringbuffer and rmt_rx_start, unlike the new driver API.
2. Espressif current ir_nec_transceiver example: https://github.com/espressif/esp-idf/blob/master/examples/peripherals/rmt/ir_nec_transceiver/main/ir_nec_transceiver_main.c . File header states Unlicense OR CC0 1.0, but this example uses the new driver/rmt_rx.h API and cannot be transplanted unchanged into IDF 4.4.
3. junkfix esp32-rmt-ir: https://github.com/junkfix/esp32-rmt-ir . MIT Arduino 3.0 / ESP IDF 5.1.4 dependency, not a drop in for the pinned IDF 4.4 firmware.
4. elrebo-de rmt_ir: https://components.espressif.com/components/elrebo-de/rmt_ir/versions/1.2.1/readme . Apache 2.0 but requires IDF 5.5+, singleton API and receiver logging only in documented version. Poor fit.

## Recommended smallest integration
Keep the existing dual legacy RMT receivers, not another library. Add source level host tests for both independent channels: complete NEC frame and inverse bit checks, malformed and truncated symbols, repeats not counting as fresh directional evidence, stale timestamp rejection, swapped receiver inputs, overflow and RMT driver errors. Maintain distinct left/right timestamps and require a fresh pair before any alignment decision. Never let IR evidence override cliff, bumper, dock contact, body fault or power interlocks. Do not derive charger enable from decoded IR.

## Hardware acceptance and provenance
Measure GPIO36/39 electrical levels and input only behavior, receiver idle polarity, ambient sunlight and LED interference, emitter identification, both receiver bearing offsets, timing jitter, dropped frames and stopping distance. Require an independent dock contact and charging verification gate. Existing source is not proof of physical operation. Cite upstream links and pin exact revisions if any code is copied.

## Coordination
Cross reference docs/hardware/full-feature-wiring-and-shopping.md, docs/reviews/PARALLEL_CHAT_HANDOFF.md and the QA findings in PR #17. This is research only, no production edits or tests. Do not create another PR. Next implementation task is one isolated malformed/repeat NEC parser regression test, followed by actual IDF 4.4 compilation when CI runners work.
