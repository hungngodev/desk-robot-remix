# Five copies of one core

All five have the same camera, OLED, microphone, speaker, N20 drive, two SG90s,
lift/gripper, WROOM and regulated power. Copy the first **physically validated**
build four times. Hats and costumes are removable covers; keep lens, acoustic
ports, OLED, USB, antenna area, power switch and full arm/track travel clear.
Avoid heavy or tall decorations that tip the rover. No costume CAD has been made.

## Software available now

Run from the project root:

```sh
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
Prepare each **qualified** modular head using its own configured identity,
rebuilding one private binary at a time; see [firmware builds](build.md):

```sh
python3 firmware/head/private_config.py --config config/local.toml --board modular --robot robot-05 --server-ip MAC_LAN_IP
bash scripts/build_head.sh --board modular --private
```

The private-config helper looks up that robot's exact token environment name.
Never flash the last robot's private binary onto another unit. No devices have
been selected or flashed. The budget camera board still needs qualification
against the reference firmware before these hardware steps apply.

After local speech/model setup and individual head audio tests:

```sh
uv run desk-robot --config config/local.toml serve
uv run desk-robot --config config/local.toml chat robot-01 robot-02 robot-03 robot-04 robot-05 --topic "Take turns naming an animal without repeating one"
```

Run the chat in a second terminal while the coordinator is running. Stop through
the authenticated `/v1/conversation/stop` endpoint. The group does not drive
automatically during conversation. Every movement/pickup still requires its own
operator permit and uses the existing watchdog/bounded-command path.

## Physical acceptance before the group plays

1. Build one, pass the gripper/power/head and 8/10-per-category pickup tests.
2. For each duplicate, prove identity isolation: status, audio, bounded movement
   and stop reach only the intended unit. A wrong mapping is a failed test.
3. With all five stationary, verify ten-turn ordering, one audible speaker at a
   time and microphone suppression. Check normal completion, stop during speech,
   one head disconnecting and coordinator loss. Verify normal listening resumes.
4. Run supervised activities in a contained flat area. There is no cliff or
   multi-robot collision sensing; the software does not promise free-roaming play.

Exact owned board/bank counts and five-unit delivered costs are unresolved. Use
[the quantity sheet](../hardware/fleet-components.csv) and
[inventory](../hardware/fleet-inventory.json); buy multiples after one passes.
