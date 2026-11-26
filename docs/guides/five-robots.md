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
timeout. One rolling five-minute allowance is shared by all group sessions,
including autonomous peer dialogue. Each logical utterance consumes one slot at
its first speaker attempt, even if interrupted; audio chunks do not each consume
a slot. Changing topics or participants does not reset the counter. The current
participant count determines the ceiling; requests are shortened to the remaining
allowance or return an empty transcript when exhausted. Individual human replies
are not subject to this peer-dialogue limit. The allowance is in-process only.
Each robot has its own persona/history; every spoken line is delivered
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
Turning off fleet sharing blocks stored secondhand stories from new proactive
context, voice recall, and native startup context, while preserving the pet's
own memories when their independent memory permission allows retrieval.
The operator can still inspect or explicitly forget retained private rows.
Revoke/regrant during those reads invalidates the outstanding read. The
shared historical prompt labels the originating pet and includes observation
age and confidence; a camera classification remains an unverified model guess.

Each private SQLite database is bound to its persistent robot ID. Renaming or
swapping already bound databases cannot make one pet inherit another's memories.
Legacy databases without a binding are migrated under their configured identity;
contradictory firsthand provenance is rejected. A legacy database containing only
preferences has no independent proof of its former identity, so verify its backup
and filename before migration. An operator correction or deletion invalidates
in-flight group speech derived from that private context, including a pending
speech memory write. This cannot undo previously audible speech or independently
stored peer copies. A completed speech receipt must not be duplicated as an
interrupted fragment when sharing consent is revoked.


The Mac now supports **explicitly consented, event-triggered two-pet social
dialogue** as well as manually requested two-to-five-pet conversation. Set
`fleet_text_sharing_enabled = true` and
`fleet_social_autonomy_enabled = true` together in the private hardware config
after confirming that every participating head can be interrupted by real
Xiaozhi VAD. The source selects a quiet, enabled peer for a recent witnessed
key, candy, object, hand-wave, petting or NFC event, rotates eligible partners,
uses the existing exclusive speaker lease, and limits the exchange to two turns.
The listening pet is told explicitly which peer witnessed the event and must
not pretend it saw that scene. A separate cooldown suppresses repetitive
invitations: both the configured invitation start interval and the normal
speech cooldown plus 20 seconds after the latest fleet speech transmission
must elapse. A transmission is not verified audible playback. Default consent
stays false; see
[the authoritative multimedia and social contract](multimodal-voice-video-orchestration.md).

### Optional daily quiet hours

In private `config/local.toml`, set `pet_quiet_hours = ["22:00", "07:00"]`
to silence unsolicited fleet speech using the Mac's actual local clock. This is
an example, not a default. The start is inclusive and the end is exclusive;
overnight windows and local daylight-saving changes follow the system clock.
An omitted window disables scheduling. Invalid or equal endpoints are rejected.
The manual per-pet quiet flag is independent and remains set after the window
ends. Explicitly requested conversation remains available; safety monitoring and
operator-owned motion permissions are unchanged. Optional speech is rechecked
before synthesis and transmission, and the existing activity task requests
cancellation of active optional speech on the next one-second policy check.
This is a host policy, not measured acoustic STOP latency.

A word game such as “Take turns naming an animal without repetition” is still
only a prompted language activity, **not** a deterministic scored game referee.
The software does not currently prove autonomous collision-safe chasing,
coordinated physical object handoff, visually verified joint manipulation or
a physical five-head acoustic trial. Pickup remains separately supervised.

## Identities and setup after one passes

Start from `config/fleet.example.toml` for a new private `config/local.toml`.
If `local.toml` already exists, merge the extra robot sections while preserving
its real addresses and calibration paths. Do not overwrite an existing setup.

| Robot | Example name | Head token environment name | Native Kokoro voice |
| --- | --- | --- | --- |
| robot-01 | Pip | DESK_ROBOT_HEAD_01_TOKEN | `af_heart` |
| robot-02 | Dot | DESK_ROBOT_HEAD_02_TOKEN | `am_adam` |
| robot-03 | Chip | DESK_ROBOT_HEAD_03_TOKEN | `af_bella` |
| robot-04 | Byte | DESK_ROBOT_HEAD_04_TOKEN | `am_michael` |
| robot-05 | Bob | DESK_ROBOT_HEAD_05_TOKEN | `af_nicole` |

Names/personas may change without changing the core. Set actual LAN addresses
and unique Xiaozhi device IDs, then reference separately measured calibration
files. Hardware examples keep motion disabled. An identical printed core does
not imply identical camera pose, motor polarity or servo endpoints.
The selected `config/fleet.hardware.example.toml` and both generic
`fleet.example.toml` and `robots.example.toml` assign the five distinct
voices above. The Mac native runner refuses duplicate voice assignments
for provisioned devices while allowing unbuilt siblings to remain without
`device_id`. Do not flash a second pet using the first pet's identity.
[Local AI setup](local-ai.md) explains the one Xiaozhi `CustomTTS` voice
owner, the unsupported provider hold and the required actual speaker
verification. Five distinct configured voice strings do not prove five
different physical voices until the heads are tested.

Extend credentials without rotating the original head/operator/model tokens:

```sh
uv run desk-robot --config config/local.toml secrets --add-missing
```

Values stay in ignored `config/local.env`, permissions 0600, hidden from output.
**The Sense source build target exists. Check the exact commit's CI result;
physical peripheral and fit tests remain open regardless of CI status.** After
it is qualified, prepare each head using its own configured identity,
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

The [original active-pet plan](../plans/2026-11-03-active-desk-pet.md) is
historical design context. The present implementation has the Mac witnessed
event and bounded social initiation gate, sensor-triggered camera capture, five
independent memories and the pinned Stackchan OLED state machine. It is **not**
an unconditionally awake or physically qualified animal-like robot: spontaneous
speech requires live authenticated Xiaozhi human-turn monitoring, opt-in,
fresh source evidence, available speech floor and cooldown. A model must never
command autonomous movement based on a social prompt. RoboEyes GPL3 is not
bundled or imported. The unbuilt power path and mechanical assembly still
prevent a claim of assembly-only readiness.


## Persistent operator-enabled exploration using the existing body controller

The Mac `POST /v1/robots/{robot_id}/explore` endpoint now starts an explicitly
operator approved, persistent exploration job after the normal one-use permit.
It never renews a two-minute operator token. It reuses the existing Coordinator
one-runner-per-robot, authenticated live XIAO MJPEG frames, WROOM 100ms pulse,
500ms watchdog, local five-channel cliff stop, touch interlock and IMU heartbeat;
it stops to reobserve after each pulse. Hardware requires a fresh, newer live
frame; synthetic snapshots are for simulation only. A disarm, status failure, missing forward clearance,
pressed touch, local stop, quiet mode or network loss cancels the job. `/stop`
remains callable with the authenticated tool token, so voice stop can preempt
exploration. Only one hardware moving job is admitted across the fleet.

For actual hardware, `exploration_qualified` defaults to false and physical
operation is refused until swept-path, side-obstacle, wheel-slip and stopping
trials support enabling it. The initial compiled navigation uses short forward
segments only. Reverse and turns are not silently inferred safe from a single
forward optical beam. Full autonomous route choice remains part of the complete
product requirement and needs verified swept-space coverage and state estimation
before enabling unrestricted traversals. The simulation tests persistent
start/stop and recovery logic; they do not establish that desk navigation is safe.
