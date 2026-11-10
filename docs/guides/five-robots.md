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

## Optional witnessed versus told peer memories

The existing Mac `PetController` can now propagate **text-only** camera scene
changes and touch events to each of the five private local SQLite databases.
Every observation has one event ID and one source robot. The observing pet keeps
`witnessed=true`; the other four store `witnessed=false` with
`source_robot` identifying the reporting pet. The existing conversational
memory builder tells a pet whether it witnessed a fact or was told by a peer.
This does not pretend five cameras saw the exact same thing.

To enable sharing explicitly, set `fleet_text_sharing_enabled = true` at the
top of a private `config/local.toml`, not inside an individual robot section.
The default and the public example are `false` to protect room privacy.
The separate `fleet_text_auto_fanout_enabled` switch defaults to `true`,
preserving automatic sharing **only after** the operator enables text sharing.
For strictly selective memory transfer, set `fleet_text_sharing_enabled = true`
and `fleet_text_auto_fanout_enabled = false`: new observations stay on their
witness robot until an operator copies a particular event to a named peer.
This still never grants any motion authority.
Neither images, audio, video files, raw model prompts nor motor permissions are
propagated between heads; the shared Mac only persists a bounded observation
description. Only a separately enabled robot's camera or touch produces its
own firsthand observation. If five cameras see a change at once, they still
have individually witnessed events, while the existing global speech owner
serializes responses and applies spontaneous cooldown.

### Operator selected one event relay, recovered from historical PR #4

With `fleet_text_sharing_enabled = true`, an operator may copy **one already
witnessed text memory** to one named peer rather than relying only on the
automatic fleet fanout. Reuse the existing Mac authenticated API; do not add
another peer database, network bus, camera stream or speech worker.

```sh
# List robot 01's recent private text memories to obtain an event ID.
curl http://127.0.0.1:8765/v1/pet/robot-01/memories?limit=12 \
  -H "Authorization: Bearer $DESK_ROBOT_API_TOKEN"

# Copy one already witnessed event to robot 03.
curl -X POST http://127.0.0.1:8765/v1/pet/robot-01/share \
  -H "Authorization: Bearer $DESK_ROBOT_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"to_robot":"robot-03","event_id":"<existing-event-id>"}'
```

Supply an actual `event_id` from the operator-only read-only memories endpoint.
It exposes bounded text and original source/witness tags, not JPEG or audio. An operator credential is mandatory; a model/tool
token alone cannot share. Repeating the same event to that peer is idempotent:
`stored=false` means no new copy was created. Each original local observation
remains `witnessed=true` only for its own camera or touch; the recipient stores
the same text, origin and observation timestamp with `witnessed=false`.
When auto fanout has already delivered that event, a manual share does not
duplicate it.

The former PR #4 could reforward secondhand stories with an explicit teller
chain. Our current schema preserves **origin identity** but does not store
intermediate tellers; to avoid falsified provenance, manual relay only accepts
firsthand source records until teller-chain support is properly designed.
Sharing does not speak, move, rearm or make recipients claim they saw a scene.

This is implemented host software with provenance tests, not measured five-head
optical overlap, physical Wi-Fi load or acoustics. `fleet_text_sharing_enabled`
should be enabled only when the user explicitly chooses local peer memory
sharing and understands these memories persist in the Mac private directory.


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
