> Updated 2026-11-12. The esp32_full firmware targets eight VL53L0X
> channels (five local safety plus three independent read-only directions) through TCA9548A 0x70, local fault latching, USB-only measured
> calibration, touch interruption and read-only range diagnostics. This is
> source files and target build profiles, not a verified compile at the current PR head, flashed, fitted or physically qualified assembly. GitHub Actions currently fails before job steps execute.
> `rearm` is local WROOM USB only, never the head, Mac or model; ordinary arm
> cannot clear a fault. See firmware-foundation.md and the verification record.

# Integration contract (implementation baseline)

The protocol is derived from VerdureBuddyRover's newline-delimited UART protocol,
with explicit motion time bounds and lift/grip extensions. It is **not** a claim
that unchanged Verdure firmware is safe or compatible with this build.

## Body UART, 115200 baud, 8N1, 3.3 V logic

Head TX GPIO2 -> body RX GPIO16; body TX GPIO17 -> head RX GPIO1. Common ground.
These are the configured modular-head GPIOs and existing WROOM-32 UART2 pins.
The previous CoreS3 reference used the same numbers on PORT.A. They are not
the new head's display/camera pins; see [module pin allocation](modular-head.md).
Use a separate regulated supply for motors/servos, never GPIO power.

Each command is one ASCII line, at most 95 characters, terminated by CRLF.
Responses are one `OK ...`, `ERR ...`, or (for status) one JSON line. Ignore `EVT`
and startup logs when waiting for an ACK; do not accept an unrelated ACK.

| Command | Behavior |
| --- | --- |
| `ping` | Link check; does not renew motion authority |
| `status` | JSON with `armed`, `motor.m0/m1`, `servo.lift/grip`, `watchdog_ms` |
| `aux` | JSON with raw accessory, 1S fuel and independent charger seat signals; never proves charging |
| `ir` | JSON with independent direct left/right 34-symbol NEC frames, 200ms freshness, matched code and zero movement/charging authority |
| `arm` / `disarm` | Operator-only session enable; start disarmed, never auto-arm |
| `drive L R MS` | Atomic signed wheel percentages (-100..100 input), capped to 40% by default; duration 1..250 ms |
| `drive L R` | Same, default 250 ms, unlike unbounded upstream behavior |
| `lift ANGLE` | Calibrated bounded servo target; initial conservative range 60..120 degrees |
| `grip ANGLE` | Calibrated bounded servo target; initial conservative range 60..120 degrees |
| `keepalive` | Renews active operator/control session, never extends a drive pulse |
| `stop` | Idempotent: zero wheels and freeze servo commanded-position ramp |

Invalid/overlong control input must not actuate; reject non-finite/non-integer and
trailing tokens. A missing valid control/keepalive for **500 ms** stops wheels and
servo ramp and disarms. Status/ping/invalid input cannot keep motion alive.
Watchdog disarm retains the last servo PWM to avoid releasing a payload;
explicit operator `disarm` detaches. Boot starts detached.
Drive duration expires independently, even with keepalive. Disarm requires a new
operator `arm` and resets targets to current commanded angles (not old targets).
At boot, set H-bridge inputs low before UART; servos stay detached until armed.
Report commanded positions honestly: hobby servos have no measured position or
grip-force feedback. Mechanical limits must be calibrated without a load first.

## Head HTTP API (port 8081)

LAN API uses `Authorization: Bearer <per-robot token>`. Empty/default token disables
control. Do not embed real tokens in Git. Serialize UART transactions and camera
access; reject oversized bodies and commands. Never auto-arm from an MCP tool.

- `GET /api/status`: body status JSON, includes `robot_id`.
- `POST /api/command`, JSON `{ "command": "drive 20 20 150" }`:
  `{ "ok": true, "reply": "OK drive ...", "robot_id": "robot-01" }`.
  Body ERR => HTTP400; UART failure/timeout => 503/504, never pretend success.
- `GET /api/aux`: raw body sensor data with independent dock seat GPIOA, no net battery charging assertion.
- `GET /api/ir`: WROOM two-channel read-only RMT NEC evidence; 34-symbol classic NEC, code checksum and fresh per-side sequences. A matched code never authorizes movement or charging.
- `GET /api/pose`: authenticated, bounded read-only WROOM pose v1. Old body firmware returns HTTP 501, not guessed coordinates.
- `GET /api/camera.jpg`: fresh JPEG using the existing camera implementation and
  image-to-JPEG helpers. No new sensor driver. Return failure if capture fails.

The active modular implementation uses `desk-robot-modular-s3` and an
`Esp32Camera` snapshot adapter; the previous `desk-robot-core-s3` reference remains
separate. The modular board uses its own audio/display pins and camera I²C0 versus
OLED I²C1, with a camera-driver Kconfig guard. Token/robot ID go in private build
configuration. Both variants retain the same API and shared camera lock. Existing
Xiaozhi camera capture and HTTP capture must not race. Common-camera changes,
if necessary, must be narrow and guarded.

Opt-in debugging MCP tools map bounded drive/stop/lift/grip/status to the same
serial transport. In normal operation the head exposes status only, and the
server plugin routes pickup and job-cancelling stop through the laptop. This
prevents an independent head tool from changing movement during a laptop job.
Keepalive only during a bounded, supervised operation; no background task that
silently maintains an abandoned movement. Manual operator arming via HTTP/USB.

## Laptop

Python package `desk_robot` under `laptop/src/desk_robot`, project-level
`pyproject.toml`, tests under `tests/`. No real movement by default. A simulated
head/body transport must exercise the same coordinator logic in tests.

Per-robot configuration: ID, display name/persona, head URL, environment-token
name, camera/pickup calibration, and explicit `motion_enabled` (default false).
Never label examples as measured calibration. Refuse pickup without valid
calibration and explicit motion enable. Use POST for movement and operator arms.

Controller uses the existing head API (including read-only WROOM telemetry),
stops in `finally` on cancel/error/lost detection,
never retries an uncertain drive ACK, bounds attempts/time, and serializes jobs
per robot. Capture -> YOLO-World detections -> calibrated pixel/ground alignment
-> short drive pulses -> grip/lift -> separate visual verification. A detection
or servo ACK alone is not proof of pickup; uncertain verification is a failure.

Expose a local FastAPI coordinator API/CLI for status, stop, supervised manual
control, image capture, pickup and a
two-to-five-robot conversation. Default localhost. Use the existing Xiaozhi server through
an overlay/plugin to route spoken pickup requests to the right robot/coordinator.
Keep model/vision/speech imports optional so base tests run without model weights.
Measured calibration is a private JSON file; human physical trials are recorded
in the CSV and summarized by `scripts/check_trials.py`, separately from the API.
Operator `/enable` grants a 30-second one-use permit for one bounded job.
For hardware mode, the coordinator first fetches the existing authenticated
Sense `/api/status` response and refuses a permit unless the actual WROOM
reports its expected stepper backend, correct robot identity, disarmed state,
unpressed touch, clear local five-channel safety and five present, valid,
recent readings. It checks **again immediately before the job arms**; a touch,
disconnect, stale reading or fault between permit and execution therefore
fails the job without requesting motor power. Missing fields fail closed.
The body itself remains the sole safety authority and rechecks sensors before
every motor output; a successful Mac preflight is not a replacement for local
USB calibration, manual safety rearm or measured stop distance.

The body is actually armed only when the job starts. Model tools have a separate
token and cannot grant permits. Keepalive runs only while the job is active.
Simulation deliberately skips physical preflight but must never count as a
physical trial.

Conversation: shared speaker lock, independent robot histories, distinct IDs,
maximum six **utterances total** for two/three participants, eight for four,
ten for five; cancellation/stop. Deliver peers' transcripts
digitally, not by listening to each other's speakers. Ollama qwen3:8b, local
SenseVoice ASR, native Kokoro HTTP TTS via Xiaozhi configuration. No automatic
paid API use. A backend/provider failure must surface, not become a fake reply.

Acceptance: real keys including a flat key, and candy; >=8/10 **physical** trials
per category, recorded separately from software/simulation results. No tests
generated by this task may claim actual gripping or success rates.


### Independent read-only terminal dock IR API

The selected WROOM `esp32_full` target installs two independent legacy ESP-IDF 4.4 RMT RX channels on **GPIO36 and GPIO39**, after moving the slow magnetic reed and PIR to MCP23017 GPIOB0/B1. The receiver code in `lib/TerminalIr` checks polarity, complete NEC 34-symbol mark/space timing, inverse address/command bytes, per-side acquisition sequences, 200ms freshness and dual matching 120ms separation. These are bounded read-only observations, not a bearing measurement or a motor permit. RMT snapshots are stamped when WROOM consumes packets, not optical exposure timestamps.

The existing XIAO serial parser explicitly permits read-only `ir`; the XIAO authenticates `GET /api/ir`, validates the JSON and forwards the correct robot ID. The Mac `HttpHead.ir_status()` rechecks the five-field identity/freshness and returns bounded typed data; the Mac adds `GET /v1/robots/{robot_id}/dock/ir` under the existing private bearer-token gate. No extra MCP server, ROS2 motor owner, charger, WiFi stack or direct HTTP-to-WROOM bridge exists. `code/tests/test_dock_ir.py`, `code/firmware/body/tests/terminal_ir_tests.cpp`, and head protocol tests cover the source protocol.

The terminal beacon's actual chosen transmitter and receiver carrier, 3.3V bias, ESP32 GPIO36/39 erratum, mechanical baffle, differential bearing geometry and charger remain physically unverified. **The source returns `physical_qualified=false`, `motor_authorized=false`, `charging_authorized=false` on every IR query.** Do not use the new endpoint as an instruction to drive toward live contacts.

### Independent capture sequence over the existing Sense camera endpoint

Each newly encoded JPEG from `/api/camera.jpg` now reports its Sense boot
nonce, monotonic per-boot frame sequence and device clock completion time in
`X-Desk-Camera-Boot`, `X-Desk-Camera-Sequence` and
`X-Desk-Camera-Complete-Us`. The existing Mac `HttpHead` serializes capture
calls within one robot, independently of its motor/status lock, and refuses
missing or replayed metadata on physical hardware. A new Sense boot nonce
correctly resets the counter. A reboot does **not** silently start pet mode.
These headers say when JPEG encoding finished on the head, not the sensor's
precise exposure time. Device and Mac monotonic clocks are not synchronized;
actual capture lag and camera/audio coexistence still require hardware tests.
Only current frames reach proactive comparison and the pickup controller.


### Read-only pose v1

This is the proposed guide 20 to guide 30 UART interface, pending actual WROOM
producer integration and measured wheel/IMU calibration. A caller must not
treat any sample as movement authority. The head issues the exact ASCII
`pose\r\n` command on the existing 115200 baud 8N1 UART mutex; the body
returns one complete JSON line. There is no arbitrary UART tunnel, background
keepalive or retry. The same per-robot bearer authentication and currently
configured head `robot_id` apply as `GET /api/ir`. The head appends
`robot_id` and a head-local `head_boot` (its Sense boot nonce) to the
nine validated body fields without modifying body timestamps or coordinates.
The Mac source reader uses `head_boot` to invalidate old pose continuity
if Sense alone reboots while WROOM remains powered.

The exact required nine body fields are `v=1`, `body_boot` (nonzero uint32),
`origin` (uint32 origin identity), `seq` (uint32 sample sequence),
`sample_us` (body monotonic sample-start microseconds, at most the exact
JSON integer range 2^53-1), `x_mm`, `y_mm` (signed 32 bit millimeters),
`yaw_mrad` (signed 32 bit milliradians), and `quality` (only `valid`,
`degraded`, or `unavailable`). All fields are integers except quality.
A valid/degraded reading requires nonzero origin, sequence and sample time. Every quality, including unavailable, requires a nonzero sequence and source sample time. Coordinates are restricted to ±1,000,000 mm and yaw to ±3,142 mrad for the current Mac pose decoder.
Unrecognized versions, omitted or extra fields, nonintegral/out-of-range
values, malformed JSON and foreign acknowledgments cannot become a pose.
No wrap/age conversion from body to head clocks is inferred by the head.

Illustrative wire fixtures only, NOT observations from installed hardware:

* Same boot and origin, first sample:
  `{"v":1,"body_boot":42,"origin":3,"seq":100,"sample_us":15000000,"x_mm":120,"y_mm":-20,"yaw_mrad":157,"quality":"valid"}`
* Later sample, same boot and origin:
  `{"v":1,"body_boot":42,"origin":3,"seq":101,"sample_us":15050000,"x_mm":121,"y_mm":-20,"yaw_mrad":158,"quality":"degraded"}`
* Rebooted body, new boot and new origin, first sample:
  `{"v":1,"body_boot":43,"origin":4,"seq":1,"sample_us":1000000,"x_mm":0,"y_mm":0,"yaw_mrad":0,"quality":"valid"}`
* Body available but pose not localized:
  `{"v":1,"body_boot":43,"origin":0,"seq":2,"sample_us":1100000,"x_mm":0,"y_mm":0,"yaw_mrad":0,"quality":"unavailable"}`

A body reboot invalidates the old frame even if its new sequence happens to
match. A new origin also invalidates old spatial coordinates. Mac guide 50
must validate robot identity, boot/origin, sequence and age, and must not
promote a degraded/unavailable or uncalibrated pose to safe navigation.

For a legacy WROOM reply `ERR input unknown_command`, the head sends
HTTP 501 and `{"ok":false,"reply":"pose unsupported by body firmware","robot_id":"robot-01"}`.
Malformed pose JSON or body-side pose errors return HTTP 503; an uncertain
no-reply returns HTTP 504 after the existing 350 ms UART bound. One pending
read shares the existing nonurgent telemetry latch; urgent STOP preempts
nonurgent UART reads at the current polling boundary. No `pose` query
renews the 500 ms body watchdog.

Camera JPEG identity is separate. Three illustrative accepted JPEG header
fixtures, with independent headset monotonic microseconds, are:

* A: `X-Desk-Camera-Boot: 123`, `X-Desk-Camera-Sequence: 1`, `X-Desk-Camera-Complete-Us: 250000`
* B: `X-Desk-Camera-Boot: 123`, `X-Desk-Camera-Sequence: 2`, `X-Desk-Camera-Complete-Us: 500000`
* C after Sense reboot: `X-Desk-Camera-Boot: 124`, `X-Desk-Camera-Sequence: 1`, `X-Desk-Camera-Complete-Us: 10000`

The last value is head monotonic microseconds at completed JPEG encoding,
not optical exposure time or body `sample_us`. A head reboot resets its
camera sequence but changes both the JPEG boot and `GET /api/pose`
`head_boot`. The Mac must not compare microsecond epochs across devices.
The camera can bracket one stationary, motor-disarmed pose estimate only
with fresh ordered pose before and after the JPEG, equal body boot and
origin, equal head boot, no intervening movement or pickup, and measured
source-to-optical latency bounds. Never treat an uncalibrated bracket as
navigation authorization. Actual optical lag and audio/camera coexistence
require physical measurement and remain unqualified.
