# Desk robot remix project instructions

**Read [docs/blueprint/README.md](docs/blueprint/README.md) before planning or implementing anything new.** The user requires a final-capability plan from day zero, preserving all 200 registered behavior/sensor/game/experimental ideas and the 131 unique HTML research links, rather than a throwaway simple robot rebuilt for proactive conversation later. Source-first remix and a no-avoidable-rework integration path take priority. The hard end experience includes independent pushed-camera conversation, contextual memory, normal speech interruption in robot one, social five-peer sessions, safe physical behavior and measured key/candy pickup. Do not mark optional sensors as physically selected, delete historical research, weaken safety, or invent power/current/price/physical test evidence. [Linear stages](docs/blueprint/linear-build.md) and [stage-zero blockers](docs/blueprint/decisions-before-hardware.md) apply before final print or purchase.

- Start at `docs/README.md`. Keep the build order in `docs/PLAN.md`, requirements in
  `docs/product-definition.md` and purchasing details in `docs/hardware/parts.md`.
  Link to the canonical page when a decision already has a home.
- Follow the recording rule in `docs/decision-log.md`. Recall durable project
  decisions from the `desk-robot-remix` Cognee dataset, update canonical project
  files when decisions change and verify durable memory writes by retrieval.
- Latest accepted decisions are canonical in `docs/product-definition.md`:
  local Mac first, proactive camera events without a spoken prompt, first-build
  ordinary-speech interruption, exploration enabled until paused/stopped, and
  Fetch/Cozmo/Vector styling. Touch and six-axis handling awareness are now
  required; RGB is optional. Do not reopen these as missing feature choices.
  Read `docs/source-map.md` and `docs/hardware/interaction-sensors.md` for source reuse
  and proposed pin/library boundaries; those are not implemented firmware.
- Current design reuses owned WROOM, SSD1306, 28BYJ-48/ULN2003 and MG90S parts.
  Latest18 photos are grouped in docs/hardware/photo-inventory-2026-11-04.md/json:
  ten module types, minimumone each, exact stock/condition unknown. Owned
  BerryIMU (likely V1) supersedes a new prototype IMU purchase pending identity,
  voltage/pin/readout/fit checks. Do not use V3/LSM6 wiring on it. MAX9814 is
  analog mic input, not MAX98357A speaker output. Separate CMY-1118 camera is
  interface-unknown; keep Sense camera. Other photo parts are optional spares.
  User reports purchasing XIAO ESP32S3 Sense, listing display $18.87; exact order
  quantity, receipt charges, arrival and revision are unconfirmed. KEEP SENSE as
  the active head. It includes camera/PDM mic. MAX98357A is the direct I²S
  speaker baseline. IMG_3902 identifies the HiLetgo HW-104 PAM8403. The bag says
  five pieces and one board is visible. Analog reuse requires a suitable DAC.
  Use one speaker path. The owned Adafruit AT42QT1010 #1374 is the prototype
  head-touch choice, superseding the TTP223 purchase. Verify the physical pad.
  No separate
  INMP441/Uno/Pico/Pi. First-build voice interruption remains required. Reuse RIO's
  exact-Sense software AEC/cancellation and Google/Pipecat live patterns before
  considering replacement. Waveshare is optional fallback only, not a shopping requirement.
  MG90S count is about10 by user estimate; bank model/current are unknown and
  user reports no readable rating label. Do not assume rated2A/3A or exact stock.
- Compiled body profiles: default esp32_stepper and explicit legacy esp32dev DC.
  Sense8MB/PDM/SSD1306 now compiles alongside Freenove/CoreS3 references. Portable
  stepper/cliff policy exists, but sensor I/O and calibration are absent: guarded
  profile cannot arm. Pet mode/animation/memory remain planned. Never equate
  compilation/host tests with physical qualification. Read docs/guides/firmware-foundation.md.
- Keep pinned upstream clones and original CAD untouched. Small mounts, bezel,
  spacers, clearance corrections, jaw tips and removable costumes only. Keys
  and wrapped candy remain targets; new chassis/arm/PCB is outside scope.
- Four downward ToFs + separate front ToF + mux are candidates. WROOM must own
  local fault-latched stop; ordinary arm cannot clear faults, local USB-only
  rearm clears only fresh healthy data and leaves motion disarmed. No blind
  retreat, automatic rearm or dependence on
  network/LLM latency. Final geometry/surface/stopping qualification is required.
- Keep hardware motion off by default. Preserve 500ms watchdog, 250ms drive,
  one-use operator permits and separate model/operator credentials. Planned
  pet session is operator-only, enabled until paused/stopped and preemptible;
  not a current command. Reconnect/restart/fault recovery cannot enable motion.
- Amazon is preferred where possible; checked alternatives are in docs/hardware/archive/supplier-comparison.md.
  The earlier Amazon basket exceeded the cap. Check the current delivered
  total against the $50 cap before ordering.
- First prototype delivered cap $50 includes already-spent money. The
  old conditional total $40.33 used the earlier owned-bank/L0X mix and is historical. The
  current compact sensors and rechargeable 1S kit need a new delivered quote.
  One-time listing price
  is not a five-unit quote. See docs/hardware/bom.json and purchase record.
- No purchases, flashing or external publishing without device/order-specific
  authorization. User instructions take precedence; local reversible work can continue.
- Use live Fusion only after inspecting active design; preserve unrelated work.
  No manufacturing geometry edits/physical successes are currently recorded.
  Compare Cozmars packaging first. Sparky v0.1.0 is the unprinted fallback.
  See `docs/product-definition.md` for the current case choices and fit status.
- Ordinary-speech barge-in is a physical acceptance gate; a config bit/build is
  not a pass. Current compiled Sense lacks reference; RIO is a reviewed MIT
  software-reference source, not yet integrated or physically qualified. Its
  echo gate can lose barge-in, so do not count muting as success. RIO pins differ
  from our Sense map. Never copy guide
  pin tables, fixed 65 mm cliff thresholds, blind retreat or RSSI localization.
- Sensors: VL53L1X is not required. The current compact candidate is four VL6180X
  downward plus one forward L0X and mux, with concealed boards/open optical
  windows. The concept's 14 mm markers are unqualified; measure coverage/stops. Read
  docs/hardware/sensor-choice.md. Do not order 25 fleet sensors before prototype tests.
- Source/license audits are in `docs/research/`. RoboEyes/TechTalkies face and
  chillibasket are GPL3 candidates, not MIT copied code. Resolve source-chain
  terms for the stepper remix and retain all CAD/software notices.
- Keep private credentials, models, captures and character memory in ignored paths.
- Run development commands from `code/`. Keep automated tests with the code
  and human-readable evidence in `docs/records/`.
- After relevant runtime changes, run affected Python/body/head tests and builds.
  Record exact commands, versions, hashes and gaps. Documentation-only updates
  need source/BOM/link/whitespace verification, not a claim of hardware validation.
