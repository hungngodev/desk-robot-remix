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

Controller uses the head API, stops in `finally` on cancel/error/lost detection,
never retries an uncertain drive ACK, bounds attempts/time, and serializes jobs
per robot. Capture -> YOLO-World detections -> calibrated pixel/ground alignment
-> short drive pulses -> grip/lift -> separate visual verification. A detection
or servo ACK alone is not proof of pickup; uncertain verification is a failure.

Expose a local FastAPI coordinator API/CLI for status, stop, supervised manual
control, image capture, pickup and a
two-robot conversation. Default localhost. Use the existing Xiaozhi server through
an overlay/plugin to route spoken pickup requests to the right robot/coordinator.
Keep model/vision/speech imports optional so base tests run without model weights.
Measured calibration is a private JSON file; human physical trials are recorded
in the CSV and summarized by `scripts/check_trials.py`, separately from the API.
Operator `/enable` grants a 30-second one-use permit for one bounded job. The
body is actually armed only when the job starts. Model tools have a separate
token and cannot grant permits. Keepalive runs only while the job is active.

Conversation: shared speaker lock, independent robot histories, distinct IDs,
maximum six **utterances total**, cancellation/stop. Deliver peers' transcripts
digitally, not by listening to each other's speakers. Ollama qwen3:8b, local
SenseVoice ASR, native Kokoro HTTP TTS via Xiaozhi configuration. No automatic
paid API use. A backend/provider failure must surface, not become a fake reply.

Acceptance: real keys including a flat key, and candy; >=8/10 **physical** trials
per category, recorded separately from software/simulation results. No tests
generated by this task may claim actual gripping or success rates.
