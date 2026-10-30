# Desk robot remix project instructions

- Read `PLAN.md`, `test-results/verification.md` and the relevant guide first.
- The active head uses separate S3-camera/OLED/audio modules and EVA's original
  case; see `docs/modular-head.md`. CoreS3 is an earlier reference, not a purchase.
- Keep upstream clones untouched and pinned. Modify overlays/local integration
  code, never unrelated repositories or global agent configuration.
- Physical tests are not represented by simulation. Never invent successful
  pickups, force feedback, playback acknowledgements or CAD exports.
- Keep hardware motion off by default. Preserve the 500 ms watchdog, 250 ms
  drive bound, one-use operator permits and separate model/operator credentials.
- No purchases, hardware flashing or external publishing without concrete user
  authorization for the selected device/order. User instructions take precedence.
- The first-robot delivered cap is $50, conditional on reusing an owned usable
  power bank and WROOM. Five identical cores are planned; only removable cosmetics
  differ. Owned counts for the fleet remain unknown. Allowances are not quotes.
- The budget camera-board listing is not qualified for the compiled Freenove
  configuration. Verify pinout, exposed GPIO, programming and case fit first.
- Keys and candy remain required. Major mechanical redesign is out of scope.
- Use Fusion MCP for live CAD only after confirming the active design. It is
  unavailable in the initial session; preserve source licenses and attribution.
- Keep credentials, models, build outputs and captures in ignored private paths.
- Run Python tests/lint, portable body tests, head overlay/protocol tests and the
  affected firmware build after relevant changes. Record exact evidence and gaps.
