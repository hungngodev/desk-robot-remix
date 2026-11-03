# Desk robot remix project instructions

- Read `PLAN.md`, `test-results/verification.md` and relevant guides first.
- Current design reuses owned WROOM, SSD1306, 28BYJ-48/ULN2003 and MG90S parts.
  No S3 is owned. Proposed new head is XIAO ESP32S3 Sense with camera/PDM mic;
  no separate INMP441, Uno, Pico or Pi is required. Inventory counts are partial.
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
- First prototype delivered cap $50, conditional target $35.45 before charges
  and missing reused parts. No unqualified five-times reuse fleet quote.
- No purchases, flashing or external publishing without device/order-specific
  authorization. User instructions take precedence; local reversible work can continue.
- Use live Fusion only after inspecting active design; preserve unrelated work.
  No geometry edits/physical successes are currently recorded.
- Source/license audits are in `docs/research/`. RoboEyes/TechTalkies face and
  chillibasket are GPL3 candidates, not MIT copied code. Resolve source-chain
  terms for the stepper remix and retain all CAD/software notices.
- Keep private credentials, models, captures and character memory in ignored paths.
- After relevant runtime changes, run affected Python/body/head tests and builds.
  Record exact commands, versions, hashes and gaps. Documentation-only updates
  need source/BOM/link/whitespace verification, not a claim of hardware validation.
