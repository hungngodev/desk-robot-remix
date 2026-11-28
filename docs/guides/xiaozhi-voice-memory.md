# Full interactive voice memory retrieval on the Mac

The complete desktop robot has private per-robot SQLite episodic memories from physical head/cap touch, FSR squeeze, twists, near-hand proximity and visual scene changes, including witnessed-versus-reported provenance. The Xiaozhi voice assistant previously could not ask the Mac to recall them.

The new `desk_robot_memories` function is registered on the existing pinned Xiaozhi local server tool layer. It reads at most **six episodic text records** and **eight operator-curated core facts** via the existing authenticated Mac API `GET /v1/pet/{robot_id}/voice-context`. The device ID is taken from the currently authenticated Xiaozhi WebSocket and mapped to its own robot; callers cannot supply another robot_id. No raw JPEGs, PCM recordings, Wi-Fi credentials or direct motion commands are returned.

For privacy this is **off by default**. To enable after reviewing your chosen voice provider and memory sharing policy, add the following one line to your local `config/local.toml` at the root settings scope:

    voice_memory_tools_enabled = true

Do not set this in a public shared config unless you intend the model provider to receive the past text as part of a conversation. The memory summary is marked untrusted data, never a new instruction, current visual evidence or physical motor permission. The model can choose to call it when asked about past interactions. It does not guarantee human-level long term semantic memory, contextual video awareness or autonomous mechanical skills.

The Xiaozhi prompt in `code/config/xiaozhi.local.example.yaml` has been revised to sound less robotic and explicitly respect real-world grounded events and interruptions, without adding unrestricted actuator controls.

## Consent, retention and operator control

All of the following root settings default to `false` and are separate permissions:

| Setting | Scope |
| --- | --- |
| `voice_memory_tools_enabled` | Read retained text through the voice-memory tool. |
| `voice_transcript_memory_enabled` | Retain model-estimated spoken words as text; requires hardware mode and voice-memory consent. |
| `fleet_text_sharing_enabled` | Permit provenance-tagged peer text; without it, voice recall filters to local-origin records. |
| `voice_vision_tools_enabled` | Permit live voice-camera context; not implied by historical memory access. |
| `room_station_context_enabled` | Permit room-station context independently of memory access; requires the room station to be enabled. |

To recall an old event, ask a natural question such as “Do you remember my key?” The registered `desk_robot_memories(question)` tool accepts an optional question of at most 240 characters; an omitted or empty question requests recent episodes, while a nonempty question requests topical retrieval. The response separates core facts, episodes, and permitted transient sensor/tool/timeline cues. A missing topical match is not evidence that an event never happened. There are no model-facing remember, correct, forget or bulk-delete commands in this tool. A spoken request to forget something is not proof that SQLite changed.

The Mac maintains separate SQLite databases for configured robot identities, with private directory and database identity checks. Episodes use count-based rolling retention: at most 250 rows per robot, ordered by observation time and event ID, not a guaranteed number of days. Core facts are separate, with up to 24 operator-curated slots per robot. Turning off voice recall, transcript retention or sharing does not itself promise deletion of previously retained records.

Use the authenticated **operator** API, not the Xiaozhi model tool credential, to inspect or change retained text. Replace the placeholders with the configured robot ID and the actual returned event ID or core slot.

| Method and path | Effect |
| --- | --- |
| `GET /v1/pet/{robot_id}/memories` | Inspect retained episodes (default 12, limit 1–50). |
| `PATCH /v1/pet/{robot_id}/memories/{event_id}` | JSON `{"summary":"corrected description"}` (1–300 characters); preserve provenance and update search. |
| `DELETE /v1/pet/{robot_id}/memories/{event_id}` | Delete the local episode and fence replay of its ID, even if already absent. |
| `GET /v1/pet/{robot_id}/core-memory` | Inspect up to 24 curated facts. |
| `PUT /v1/pet/{robot_id}/core-memory/{slot}` | JSON `{"value":"corrected preference"}` (1–200 characters). |
| `DELETE /v1/pet/{robot_id}/core-memory/{slot}` | Remove the local curated fact. |

Check the returned `corrected`, `changed` or `removed` result; a superseded mutation can return HTTP 409. A false episode deletion result means no row was removed, not that replay protection failed. Episode deletion also removes associated spatial and camera provenance rows and updates the full-text search index. A changed episode summary invalidates its spatial sighting. Explicit edits fence older writes; the episode replay ledger is not evicted with rolling retention, and reaching its 100,000-ID bound seals new episode inserts rather than silently discarding replay protection.

Corrections and deletions are local to the selected pet. They do not automatically erase copies already retained by other pets, external model providers, backups or previously delivered speech. Inspect and delete corresponding peer records separately where applicable. Revoking consent or changing the private-memory revision during retrieval invalidates outstanding voice recall; successful operator edits invalidate affected live prompt context. SQLite enables secure deletion, but this is not a guarantee of forensic erasure of every historical copy.

## G005 dream provenance boundary

Dreams and next-day storytelling remain an expansion feature; this boundary does not start a dream scheduler. A future consented producer must persist generated dreams as `kind="fictional_dream"` (the legacy `dream` kind is also classified as fictional). A locally authored dream uses the existing local-origin bit internally, not a physical witness claim. Corrections and peer copies retain its immutable kind. Proactive and group memory context, native startup context and Xiaozhi voice recall identify it as imagined, not a physical observation. The API reports fictional records with `fictional=true`, `witnessed=false`, no physical observation time or factual confidence, and a separate recording time. Fictional episodes cannot acquire camera receipts or spatial sightings, including legacy rows with contradictory receipts. No new memory store or movement authority is introduced.
