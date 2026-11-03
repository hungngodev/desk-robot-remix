# Five active desk pets

Five identical inexpensive tracked robots, each with a camera, OLED face,
conversation, lift/gripper and local edge sensing. Different hats/costumes share
the same core. One Mac supplies speech, vision and language models. Build one
working robot before repeating it four times.

**Updated 2026-11-03:** reuse your WROOM-32, SSD1306 OLED, 28BYJ-48/ULN2003
motors and positional MG90S servos. You own **no ESP32-S3**. Candidate new head:
XIAO ESP32S3 **Sense**, including camera and PDM microphone, plus amplifier and
speaker. No extra Uno, Pico or Pi is needed.

**Cost target: $35.36 before delivery/tax**, conditional on two usable owned
MG90S servos and a suitable owned bank. **First-robot delivered cap: $50**;
charges, missing inventory and fit remain unresolved. This is not a full fleet
quote or an order-ready robot. [Components](hardware/parts.md),
[inventory](hardware/fleet-inventory.json), [budget evidence](docs/research/2026-11-03-head-budget.md).

## Start here

1. [Product shape, behavior and acceptance](docs/product-definition.md),
   [master plan](PLAN.md) and [implementation tasks](docs/plans/2026-11-03-active-desk-pet.md).
2. [Stepper chassis and wheel originals](cad/originals/smars-stepper/README.md),
   [saved gripper/lift](docs/first-gripper-test.md) and [rounded head candidate](cad/originals/sparky-head/README.md).
3. [Sense head adaptation](docs/modular-head.md), [proposed wiring/power](hardware/wiring.md)
   and [edge-sensor layout](docs/research/2026-11-03-cliff-sensors.md).
4. [Twelve-video audit](docs/research/2026-11-03-video-audit.md) and
   [active behavior / aesthetic sources](docs/research/2026-11-03-active-pet-sources.md).
5. [Existing local AI setup](docs/local-ai.md), [five-robot identity/turn-taking](docs/five-robots.md)
   and [verification limits](test-results/verification.md).

The revised design uses **four downward floor sensors, one separate front
obstacle sensor and an I²C mux**, controlled locally by the WROOM. Proposed pet
behavior adds curiosity, rest, attention and peer activities with human-enabled
bounded motion. Begin with stationary expression; then one moving robot at a
time in a qualified clear area. Portable cliff-fault policy is implemented, but actual sensor acquisition and
calibration are not; the new stepper build refuses arming. Active roaming remains
unimplemented. A sensor arrangement alone does not guarantee against falling.

## What already works in software

The new Sense-head target and stepper/DC body profiles compile. Stepper timing,
sensor fault policy and local-only recovery have host tests; actual sensor I/O
and measured calibration are unfinished. Five-robot mock conversation still works.
See [implementation progress](docs/firmware-foundation.md). No robot has
been flashed, assembled or physically accepted; original manufacturing CAD is unchanged.
[Source-based concept views](cad/concepts/2026-11-03-rounded/README.md) exist,
with illustrative mechanisms and no fitted power bank.

```sh
uv sync --extra dev
uv run desk-robot --config config/fleet.simulation.toml demo
uv run desk-robot --config config/fleet.example.toml doctor
python3 scripts/check_budget.py
```

The demo uses generated images and mock speech, gives five IDs ten utterances,
and reports `physical_acceptance_pass=false`. It does not demonstrate live models,
real speech, gripping, cliffs or pet autonomy. Hardware examples keep motion off.
Keep credentials private; `secrets --add-missing` preserves existing tokens.

Existing controls boot disarmed, use 250 ms bounded drive, a 500 ms watchdog,
one-use operator permits and separate model/operator credentials. Local sensor-fault policy is implemented, but not yet wired to real ToF reads.
Ordinary arm cannot clear its latch; recovery is local USB only. A separate
operator-granted pet-mode lease remains planned, not an available command. Watchdog stop holds servo PWM; explicit disarm releases it.

## Source organization

- `upstream-lock.json`, `upstream/`: pinned, untouched source copies.
- `firmware/`, `laptop/`: existing integrations; new tasks clearly marked in plan.
- `cad/`, `hardware/`: original file provenance, inventory, proposed wiring and BOM.
- `docs/research/`: dated source/price audits, not full video transcripts.
- `test-results/`: historical software evidence and empty physical trial records.

Restore sources with `python3 scripts/restore_upstreams.py`. Preserve
[attribution and license boundaries](ATTRIBUTION.md); GPL face libraries are
candidates, not MIT code already incorporated. Use the live Fusion MCP only after
checking the active design when small precision CAD edits become necessary.
