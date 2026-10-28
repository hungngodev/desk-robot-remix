# Desk robot CoreS3 Lite

Unique `desk-robot-core-s3` variant of the pinned Xiaozhi CoreS3 board. Retains the
stock camera, audio, display, touch, power management and all their pin assignments.
The display controller/revision and real camera capture still require hardware testing.

Robot UART1: head TX GPIO2 -> WROOM RX16; WROOM TX17 -> head RX GPIO1, 115200 8N1,
3.3 V logic and shared ground. PORT.A becomes UART and cannot simultaneously be I2C.
Motor and servo power must use the separately sized regulated supply.

Configure `CONFIG_DESK_ROBOT_ID` and a unique private `CONFIG_DESK_ROBOT_TOKEN`
(32..128 printable non-space characters) in a private build configuration. Empty,
short, or placeholder tokens disable the entire robot bridge and movement tools.
The token is a LAN credential, not a cloud API key. Never publish the resulting
sdkconfig, private variant, or token-bearing binaries.

Authenticated LAN API port 8081:

- GET `/api/status`: body JSON with robot_id, or explicit UART error.
- POST `/api/command`: application/json `{"command":"drive 20 20 150"}`.
- GET `/api/camera.jpg`: fresh JPEG using existing EspVideo/image_to_jpeg.

All endpoints require `Authorization: Bearer <token>`. No CORS or remote Internet
exposure is configured. HTTP is for the trusted local network only.

Only an authenticated operator may send `arm`, `disarm`, or individual
`keepalive` commands through HTTP. MCP exposes drive, lift, grip, stop, status;
it cannot arm or send keepalives. There is no background keepalive. The WROOM
starts disarmed, expires control after 500 ms, and caps drive pulses at 250 ms.
UART timeouts are failures and are never retried automatically. A timeout can
mean an action executed without the acknowledgement reaching the head.

Body servo values are commanded positions, never measured position/grip feedback.
MCP/HTTP capture+encoding and the upstream capture+Explain sequence share one
camera lock. Snapshots may wait for an active photo explanation to finish.
