# Xiaozhi human interruption now cancels Mac speech too

The established XIAO Sense firmware streams real microphone audio through Xiaozhi's AFE and VAD. The existing speech bridge already issues urgent decoder/DMA flushes for confirmed double talk. **Previously**, when that happened, a Mac proactive pet comment or peer conversation could continue in a separate task.

The server now records only an authenticated, bounded and replayable human VAD interruption event from the current registered device connection. `GET /events?after=N` is restricted to the same private loopback bearer token and sends no PCM, transcript, camera content or motor action. A new server instance resets the cursor. Older events are not replayed at Mac bootstrap.

The Mac hardware runtime now starts `VoiceEventListener`, validates ordered real events and invokes `pet.interrupt()` plus `conversation.stop()`. The callback processes each event only after confirming its device identity and server origin. If the Mac falls behind the 128-event buffer, all robot TTS is canceled rather than continuing an obsolete group turn.

This completes a missing **software** cancellation propagation link, not a proof of full duplex conversational performance. Actual acoustic AEC, word capture and audio output delay must pass the target's 19/20 ordinary-speech trials. The head's urgent stop still has no physical DMA completion acknowledgement. No extra software event grants movement or authorizes battery charging.


## November 11: monitor health is a separate prerequisite for spontaneous speech

The Mac previously canceled an active speech task when the Xiaozhi event feed failed, but that alone left a gap: after a 120 second cooldown, a proactive camera event could start speaking again even while VAD interruption detection was unavailable.

The existing authenticated `VoiceEventListener` now reports health transitions to the original `Runtime`, which updates the existing `PetController` speaker gate. In hardware mode, spontaneous speech is disabled at startup until the first valid, authenticated event-stream bootstrap. A reset, lost event cursor, or transport exception marks the monitor unavailable and cancels the shared audio floor. A successful ordered authenticated poll marks connection readiness again. `_consider_speech` checks this before allocating a background model response; `_speak` checks again after any slow model response and before sending text to the existing speaker lease. Operator enablement and local physical safety permissions remain independent.

The health bit means **authenticated event transport connected**, not **human definitely silent**. If an entire speech-start event is lost during an outage, a later healthy empty poll does not provide an authoritative current VAD state. A fully qualified deployment needs a server-provided live speech-state snapshot or an explicit conservative rearming policy after gaps, plus real acoustic and network disconnect trials. This patch does not invent those measurements. Existing voice event, runtime-priority and pet tests now include loss, recovery and suppression cases; committed tests are not proof they executed. GitHub Actions currently fails with no usable job steps or logs.


## November 11: authenticated current VAD snapshot closes the missed-edge recovery gap

The existing Xiaozhi `GET /events` endpoint now includes `active_human_robots`, a sorted list of mapped, *currently connected* robots with an outstanding real debounced idle VAD `speech_start`. It is generated from the server's existing `idle_voice_emitted` and registered connections, not from a guessed microphone state, replayed text, model output or clock deadline. The same private endpoint provides this field during bootstrap, cursor reset, gap responses and regular polling; it never returns audio, transcript or camera media. AEC `normal` and `group` are excluded because they do not guarantee paired idle speech-end events.

The Mac listener validates that every snapshot identity belongs to the configured robot set and forwards the authenticated state to `Runtime._on_voice_snapshot`. If the server reports a human speaking after the Mac missed the original start event, the existing five-pet audio owner is preempted and `CameraFrameHub` holds human priority. If the authoritative server reports that an explicit idle VAD turn has ended but the end event was missed, the Mac releases that old indefinite hold; bounded AEC voice windows are preserved. Current state is reconciled on each successful authenticated poll, including recovery after an event-ring gap. Regression tests cover server source identity, missed start, missed end, overlapping AEC hold, forged robot IDs and duplicate snapshot handling.

**Limits:** This is software current-state reconciliation, not a guarantee the physical microphone or AEC classified a real human correctly. Reconnects occurring exactly during device unregister/re-register, server restarts, or lag between a server snapshot and client processing still need real network fault injection and acoustic tests. An older server without `active_human_robots` cannot provide this recovery guarantee; its event-only compatibility path is not certified for unplugged fleet operation. GitHub Actions failures with no recorded steps still prevent a claim of passing integration tests.
