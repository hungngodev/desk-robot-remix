# Desk robot remix

A personal, experimental SMARS rover with a lift-and-grip arm, a head assembled
from separate camera/screen/audio modules inside an existing EVA Robot case,
and an owned ESP32-WROOM-32 body controller. Two robots share the Mac and take
turns speaking. Build one first.

**Current stage: modular-head firmware builds and original print files are
saved; physical assembly and pickup tests remain.** The WROOM firmware and new
Freenove/OLED head compile; 65 focused software checks pass. A simulated pickup
and six-turn conversation run locally. Hardware remains unflashed and untested;
simulation does not establish that a flat key can be picked up by the mechanism.

**Budget:** current allowance-based parts total **$117.33** before shipping/tax,
including about **$39 for head electronics**. First robot has a $150 spending cap.
Speaker, motors, battery and mechanical fit are not finalized; there is no
complete verified shopping basket yet. [Parts and budget](hardware/parts.md).

## Start here

1. [Review the module head and saved case](docs/modular-head.md). The 1.3-inch OLED
   gives monochrome emotion symbols/text initially; camera, microphone and speech
   remain included. Smooth eye animation needs a later adapter.
2. [Print and bench-test the gripper](docs/first-gripper-test.md) with your actual
   flat key and candy before buying the full rover and head.
3. Follow [wiring and power](hardware/wiring.md) and [firmware builds](docs/build.md).
4. Set up [local speech and vision](docs/local-ai.md).
5. [Measure and test pickup, then add the second robot](docs/pickup-and-two-robots.md).

Only small jaw tips, spacers and mounting brackets are in scope. Fusion MCP is
not available in this session, so no CAD edits have been made. If a flat key
requires a new arm/chassis, revisit the remix choice before spending more.

## Try the software now

From this folder:

```sh
uv sync --extra dev
uv run desk-robot --config config/simulation.toml demo
uv run desk-robot secrets
uv run desk-robot doctor
```

The demo uses generated test images and mock speech, with no physical hardware
or model downloads. It explicitly reports `physical_acceptance_pass=false`.
Credentials are created once, hidden from output and excluded from version
control in `config/local.env`. Hardware examples have movement disabled.

The body boots disarmed, caps drive at 40% PWM and 250 ms, and stops after 500 ms
without valid control. Watchdog stop holds the last servo PWM; explicit disarm
detaches it. Positions are commanded estimates, not sensor readings. A human
grants one bounded laptop job a 30-second single-use permission; model tools
have separate credentials and cannot grant that permission.

## Sources and folders

| Function | Existing project |
| --- | --- |
| Chassis/tracks | [SMARS](https://www.thingiverse.com/thing:2662828) |
| Lift/gripper | [Bluino SMARS arm](https://www.thingiverse.com/thing:4253681) |
| Head case/component layout | [EVA Robot](https://github.com/Ksirailway-base/EVA-Robot), [saved 3MF](cad/originals/eva-head/EVA-Robot.3mf) |
| Camera/screen/audio drivers | [Xiaozhi S3 camera + breadboard targets](https://github.com/78/xiaozhi-esp32) |
| UART approach | [VerdureBuddyRover](https://github.com/maker-community/VerdureBuddyRover) |
| Voice server | [Xiaozhi server](https://github.com/xinnan-tech/xiaozhi-esp32-server) |

- `PLAN.md`: accepted scope and progress.
- `upstream-lock.json`, `upstream/`: exact revisions and untouched sources.
- `firmware/`: WROOM body, active modular S3 head and previous CoreS3 reference.
- `laptop/`: local coordinator and small Xiaozhi server adapter.
- `cad/`, `hardware/`, `config/`: source register, parts, wiring and examples.
- `docs/`, `test-results/`: build guides, contracts and verification evidence.

Restore sources with `python3 scripts/restore_upstreams.py`; review costs with
`python3 scripts/check_budget.py`. See [verification](test-results/verification.md)
and [attribution](ATTRIBUTION.md) for limitations, checks and licenses.

