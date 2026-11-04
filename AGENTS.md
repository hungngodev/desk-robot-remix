# Desk robot remix project instructions

- Read `PLAN.md`, `test-results/verification.md` and relevant guides first.
- Current design reuses owned WROOM, SSD1306, 28BYJ-48/ULN2003 and MG90S parts.
  User reports purchasing XIAO ESP32S3 Sense, listing display $18.87; exact order
  quantity, receipt charges, arrival and revision are unconfirmed. KEEP SENSE as
  the active head. It includes camera/PDM mic; retain MAX98357/speaker, no separate
  INMP441/Uno/Pico/Pi. First-build voice interruption remains required. Reuse RIO's
  exact-Sense software AEC/cancellation and Google/Pipecat live patterns before
  considering replacement. Waveshare is optional fallback only, not a shopping requirement.
  MG90S count is about10 by user estimate; bank model/current are unknown and
  user reports no readable rating label. Do not assume rated2A/3A or exact stock.
- Compiled body profiles: default esp32_stepper and explicit legacy esp32dev DC.
  Sense8MB/PDM/SSD1306 now compiles alongside Freenove/CoreS3 references. Portable
  stepper/cliff policy exists, but sensor I/O and calibration are absent: guarded
  profile cannot arm. Pet mode/animation/memory remain planned. Never equate
  compilation/host tests with physical qualification. Read docs/firmware-foundation.md.
- Keep pinned upstream clones and original CAD untouched. Small mounts, bezel,
  spacers, clearance corrections, jaw tips and removable costumes only. Keys
  and wrapped candy remain targets; new chassis/arm/PCB is outside scope.
- Four downward ToFs + separate front ToF + mux are candidates. WROOM must own
  local fault-latched stop; ordinary arm cannot clear faults, local USB-only
  rearm clears only fresh healthy data and leaves motion disarmed. No blind
  retreat, automatic rearm or dependence on
  network/LLM latency. Final geometry/surface/stopping qualification is required.
- Keep hardware motion off by default. Preserve 500ms watchdog, 250ms drive,
  one-use operator permits and separate model/operator credentials. Proposed
  pet lease is operator-only, expiring and preemptible; not a current command.
- Amazon is preferred where possible; checked alternatives are in hardware/amazon-parts.md.
  Do not apply supplier prices to Amazon or silently raise the $50 cap; current
  Amazon-only package spend exceeds it before power parts/charges.
- First prototype delivered cap $50 includes already-spent money. Conditional
  total $40.33 includes assumed one Sense at reported $18.87 plus $21.46 further
  parts/allowances, before charges/missing inventory. One-time listing price
  is not a five-unit quote. See hardware/bom.json and purchase record.
- No purchases, flashing or external publishing without device/order-specific
  authorization. User instructions take precedence; local reversible work can continue.
- Use live Fusion only after inspecting active design; preserve unrelated work.
  No manufacturing geometry edits/physical successes are currently recorded.
  User chose a rounder existing head: Sparky v0.1.0 is the unprinted fit-check
  candidate, EVA is historical. Read docs/product-definition.md and the new
  source-based layout views; tracks/mechanism/mounts are placeholders, bank not fitted.
- Ordinary-speech barge-in is a physical acceptance gate; a config bit/build is
  not a pass. Current compiled Sense lacks reference; RIO is a reviewed MIT
  software-reference source, not yet integrated or physically qualified. Its
  echo gate can lose barge-in, so do not count muting as success. RIO pins differ
  from our Sense map. Never copy guide
  pin tables, fixed 65 mm cliff thresholds, blind retreat or RSSI localization.
- Sensors: VL53L1X is not required. Prototype L0X samples need measured near-field
  mounting; the concept's 14 mm markers are unqualified. L0X raised 40–60 mm starting
  range may widen the robot; VL6180X is a compact near-range fallback. Read
  hardware/sensor-choice.md. Do not order 25 fleet sensors before prototype tests.
- Source/license audits are in `docs/research/`. RoboEyes/TechTalkies face and
  chillibasket are GPL3 candidates, not MIT copied code. Resolve source-chain
  terms for the stepper remix and retain all CAD/software notices.
- Keep private credentials, models, captures and character memory in ignored paths.
- After relevant runtime changes, run affected Python/body/head tests and builds.
  Record exact commands, versions, hashes and gaps. Documentation-only updates
  need source/BOM/link/whitespace verification, not a claim of hardware validation.
