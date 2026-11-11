# Xiaozhi human interruption now cancels Mac speech too

The established XIAO Sense firmware streams real microphone audio through Xiaozhi's AFE and VAD. The existing speech bridge already issues urgent decoder/DMA flushes for confirmed double talk. **Previously**, when that happened, a Mac proactive pet comment or peer conversation could continue in a separate task.

The server now records only an authenticated, bounded and replayable human VAD interruption event from the current registered device connection. `GET /events?after=N` is restricted to the same private loopback bearer token and sends no PCM, transcript, camera content or motor action. A new server instance resets the cursor. Older events are not replayed at Mac bootstrap.

The Mac hardware runtime now starts `VoiceEventListener`, validates ordered real events and invokes `pet.interrupt()` plus `conversation.stop()`. The callback processes each event only after confirming its device identity and server origin. If the Mac falls behind the 128-event buffer, all robot TTS is canceled rather than continuing an obsolete group turn.

This completes a missing **software** cancellation propagation link, not a proof of full duplex conversational performance. Actual acoustic AEC, word capture and audio output delay must pass the target's 19/20 ordinary-speech trials. The head's urgent stop still has no physical DMA completion acknowledgement. No extra software event grants movement or authorizes battery charging.
