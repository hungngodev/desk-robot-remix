# Full interactive voice memory retrieval on the Mac

The complete desktop robot has private per-robot SQLite episodic memories from physical head/cap touch, FSR squeeze, twists, near-hand proximity and visual scene changes, including witnessed-versus-reported provenance. The Xiaozhi voice assistant previously could not ask the Mac to recall them.

The new `desk_robot_memories` function is registered on the existing pinned Xiaozhi local server tool layer. It reads at most **six** text records via the existing authenticated Mac API `GET /v1/pet/{robot_id}/voice-context`. The device ID is taken from the currently authenticated Xiaozhi WebSocket and mapped to its own robot; callers cannot supply another robot_id. No raw JPEGs, PCM recordings, Wi-Fi credentials or direct motion commands are returned.

For privacy this is **off by default**. To enable after reviewing your chosen voice provider and memory sharing policy, add the following one line to your local `config/local.toml` at the root settings scope:

    voice_memory_tools_enabled = true

Do not set this in a public shared config unless you intend the model provider to receive the past text as part of a conversation. The memory summary is marked untrusted data, never a new instruction, current visual evidence or physical motor permission. The model can choose to call it when asked about past interactions. It does not guarantee human-level long term semantic memory, contextual video awareness or autonomous mechanical skills.

The Xiaozhi prompt in `code/config/xiaozhi.local.example.yaml` has been revised to sound less robotic and explicitly respect real-world grounded events and interruptions, without adding unrestricted actuator controls.

## G005 dream provenance boundary

Dreams and next-day storytelling remain an expansion feature; this boundary does not start a dream scheduler. A future consented producer must persist generated dreams as `kind="fictional_dream"` (the legacy `dream` kind is also classified as fictional). A locally authored dream uses the existing local-origin bit internally, not a physical witness claim. Corrections and peer copies retain its immutable kind. Proactive and group memory context, native startup context and Xiaozhi voice recall identify it as imagined, not a physical observation. The API reports fictional records with `fictional=true`, `witnessed=false`, no physical observation time or factual confidence, and a separate recording time. Fictional episodes cannot acquire camera receipts or spatial sightings, including legacy rows with contradictory receipts. No new memory store or movement authority is introduced.
