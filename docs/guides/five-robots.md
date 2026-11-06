# Five copies of one core

Updated 2026-11-03: the proposed core has Sense camera/PDM mic, owned SSD1306,
amplifier/speaker, two 28BYJ-48/ULN2003 drives, two positional MG90S servos,
four floor sensors, a separate front ToF, mux and lift/gripper, WROOM and regulated power. Copy the first **physically validated**
build four times. Hats and costumes are removable covers; keep lens, acoustic
ports, OLED, USB, antenna area, power switch and full arm/track travel clear.
Avoid heavy or tall decorations that tip the rover. No costume CAD has been made.

## Software available now

From the repository root:

```sh
cd code
uv run desk-robot --config config/fleet.simulation.toml demo
```

This uses generated camera images and mock conversation/speech, then reports
`physical_acceptance_pass=false`. It exercises a simulated pickup and **ten total
utterances**, robot-01 through robot-05 twice. It does not run the real LLM/audio
models or verify physical robot interaction.

A session supports two to five distinct IDs. Defaults and hard limits are six
utterances for two/three, eight for four, ten for five, with a five-minute overall
timeout. Each robot has its own persona/history; every spoken line is delivered
digitally to all the other histories. One transmission at a time, with all
participating microphones suppressed during coordinated speech. Stop/disconnect
paths are tested; measured sound/playback timing still needs physical tests.

Try a bounded word game with the local models after real speech setup, e.g.
“Take turns naming a new animal; do not repeat a previous animal.” This is a
conversation prompt, not a deterministic game referee. Autonomous chasing,
collision avoidance, object handoff and camera-grounded group chat are not
implemented. Pickup remains a separate supervised, camera-guided job.

## Identities and setup after one passes

Start from `config/fleet.example.toml` for a new private `config/local.toml`.
If `local.toml` already exists, merge the extra robot sections while preserving
its real addresses and calibration paths. Do not overwrite an existing setup.

| Robot | Example name | Head token environment name |
| --- | --- | --- |
| robot-01 | Pip | DESK_ROBOT_HEAD_01_TOKEN |
| robot-02 | Dot | DESK_ROBOT_HEAD_02_TOKEN |
| robot-03 | Chip | DESK_ROBOT_HEAD_03_TOKEN |
| robot-04 | Byte | DESK_ROBOT_HEAD_04_TOKEN |
| robot-05 | Bob | DESK_ROBOT_HEAD_05_TOKEN |

Names/personas may change without changing the core. Set actual LAN addresses
and unique Xiaozhi device IDs, then reference separately measured calibration
files. Hardware examples keep motion disabled. An identical printed core does
not imply identical camera pose, motor polarity or servo endpoints.

Extend credentials without rotating the original head/operator/model tokens:

```sh
uv run desk-robot --config config/local.toml secrets --add-missing
```

Values stay in ignored `config/local.env`, permissions 0600, hidden from output.
**Sense now compiles, but physical peripheral/fit tests remain.** After it is
qualified, prepare each head using its own configured identity,
rebuilding one private binary at a time; see [firmware builds](build.md):

```sh
python3 firmware/head/private_config.py --config config/local.toml --board sense --robot robot-05 --server-ip MAC_LAN_IP
bash scripts/build_head.sh --board sense --private
```

The private-config helper looks up that robot's exact token environment name.
Never flash the last robot's private binary onto another unit. No devices have
been selected or flashed. The separate Sense camera/PDM/SSD1306/8 MB build is available. It must still pass
actual camera, OLED, microphone, speaker, UART, power and case tests per unit.

After local speech/model setup and individual head audio tests:

```sh
uv run desk-robot --config config/local.toml serve
uv run desk-robot --config config/local.toml chat robot-01 robot-02 robot-03 robot-04 robot-05 --topic "Take turns naming an animal without repeating one"
```

Run the chat in a second terminal while the coordinator is running. Stop through
the authenticated `/v1/conversation/stop` endpoint. The group does not drive
automatically during conversation. Current movement/pickup still requires its own operator permit and existing
watchdog/bounded-command path. Planned pet mode uses a separate expiring
operator lease, never model-authorized arming.

## Physical acceptance before the group plays

1. Build one, pass the gripper/power/head and 8/10-per-category pickup tests.
2. For each duplicate, prove identity isolation: status, audio, bounded movement
   and stop reach only the intended unit. A wrong mapping is a failed test.
3. With all five stationary, verify ten-turn ordering, one audible speaker at a
   time and microphone suppression. Check normal completion, stop during speech,
   one head disconnecting and coordinator loss. Verify normal listening resumes.
4. Qualify the proposed local cliff interlock and sensor geometry before table
   activity. Only one robot moves at a time in a reserved contained patch; peers
   may animate/talk. Front ToF is not all-direction collision avoidance.
5. Later, qualify simultaneous motion before allowing all-five free roaming,
   chasing or physical object handoff. These are not implemented capabilities.

Exact owned board/bank counts and five-unit delivered costs are unresolved. Use
[the quantity sheet](../hardware/fleet-components.csv) and
[inventory](../hardware/fleet-inventory.json); buy multiples after one passes.

## Planned initiative, not only replies

The [active-pet plan](../plans/2026-11-03-active-desk-pet.md) adds local idle eyes
and a Mac event scheduler: curiosity, rest, attention requests, bounded exploration
and peer invitations. Distinct per-ID persistent memories and cooldowns avoid
identity mixups and endless peer chatter. Start stationary, then human-enabled
short motion; stops/faults/lease expiry cancel queued activity with no auto-resume.
RoboEyes is GPL3 and needs an ESP-IDF adapter. No new face/pet/cliff code is
implemented by the documentation update.
