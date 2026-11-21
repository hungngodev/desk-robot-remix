# Live conversation integration contract

Implemented 2026-11-03: original, transport-independent state in
`laptop/src/desk_robot/live_turns.py`. This is tested offline logic, not a working
microphone, echo canceller, Gemini connection or streamed camera. It does not
change the WROOM interlocks or grant permission to move.

The active hardware is the user's purchased XIAO ESP32S3 Sense, existing OLED,
external MAX98357/speaker and WROOM body. [Pinned reuse sources](../research/2026-11-03-sense-realtime-reuse.md)
provide the device AEC and native live-session integration direction. Keep the
current compiled [Sense pin map](../../code/firmware/head/sense/README.md) until the port
is reviewed. No additional microphone or replacement board is required now.

## What the offline core supplies

- A generation/turn identifier rejects delayed audio from an obsolete answer.
  An interruption clears the Mac playback queue and produces an explicit device
  flush instruction. The default buffer is 9,600 bytes, equivalent to 200 ms of
  mono 24 kHz 16-bit PCM; overflow must be handled, not silently accumulated.
- A single latest-frame slot bounds camera memory. Sending is paced at one frame
  per second by default, with a two-second freshness limit. These are initial
  integration settings, not measured Sense throughput or recognition accuracy.
- Explicitly enabled observations use a fresh image and a short contextual
  prompt only while idle. User speech, generation/playback, tools and quiet mode
  suppress them. Reconnection does not restart proactive observations silently.
  The default 30-second observation interval does not authorize speech every
  30 seconds: the pet/fleet layer must apply its stricter speech cooldowns.

## Adapter responsibilities

1. Use one event-loop owner. Marshal off-thread microphone/camera/codec callbacks
   to it. Capture the request's turn/connection identity when work starts, and
   retain it through every callback; a late callback must not become current by
   reading the latest identity. `offer_frame` requires the capture producer's
   `connection_epoch`, `captured_at` and reception `now`; `set_busy` requires the
   work's turn epoch. Recheck identities after each asynchronous wait and before
   transport sends. Reconcile old busy flags explicitly after cancellation or
   reconnect; a late old completion must not clear them on a newer turn.
2. Feed real echo-clean microphone audio continuously. Port and calibrate RIO's
   playback-reference approach; it is separate from the Mac queue controller.
   Resampling, acoustic delay, double talk and motor noise need measured tests.
3. On an interruption, cancel the old provider/request and decoder, flush the Mac
   queue, send the explicit flush to the Sense and clear pending device output.
   Already queued I²S/DMA samples do not disappear when a Python queue is cleared.
   Keep the new utterance. Observe actual silence latency at the speaker.
   Forward `ObservationRequest.flush` before dispatching a new idle observation,
   and forward flushes returned by connection, turn, quiet and opt-out changes.
4. Keep the model busy through generation **and device playback completion**.
   Keep tool activity busy until it stops. Clear busy state only for the current
   work; an obsolete completion must not declare a newer turn idle.
5. Capture independently and send only fresh paced frames. RIO's power-cycled,
   tool-requested still capture is not continuous video. Avoid starting a
   proactive prompt while another turn/tool is active. Capture and receipt times
   must use a common monotonic clock: map a device capture timestamp explicitly;
   do not relabel an old image's network receipt time as its capture time.
6. Put one coordinator per robot inside the existing fleet turn arbiter. Keep
   keys private, cloud sessions opt-in, and stop/arm/motion authority within the
   existing guarded controller. Session loss never authorizes roaming.

See [mandatory physical voice trials](audio-barge-in.md). Mocked tests establish
state transitions and cancellation behavior only; no assembled robot has passed
voice, camera, edge, power or pickup acceptance.


## Authenticated device interrupt recovered from closed PR #7

The current Xiaozhi server adapter now exposes its original authenticated
`POST /interrupt` endpoint on the existing local speech bridge port 8766.
`KokoroHeadSpeaker.interrupt` already calls this route when Mac proactive
speech is cancelled. Before recovery, that call targeted a missing endpoint,
so a cancelled Python task could leave audible device audio running.

```sh
curl -X POST http://127.0.0.1:8766/interrupt \
  -H "Authorization: Bearer $DESK_ROBOT_SPEECH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"device_id":"<real-private-xiaozhi-device-id>"}'
```

The bridge rejects unregistered or unknown head IDs. The target head receives
`{"type":"tts","state":"stop","flush":true}` on its existing WebSocket,
matching the current Sense urgent decoder and I2S output reset rather than the
older PR #7 `tts abort` shape. This call does not wait for the fleet speaker
lock. A per-device generation counter rejects older speech requests waiting
on the global lock, encoding in the worker pool or already streaming, and does
not cancel an unrelated robot's playback.

Automatic user speech interruption through AEC/VAD also advances that
generation. The returned `head_flush_requested=true` only means that the
server sent the stop frame; `head_flush_acknowledged=false` and
`audible_stop_verified=false` remain the truthful status until a real Sense
microphone, speaker, DMA and room test establishes stop latency and 19/20
successful natural speech interruptions within 500 ms.
