# Natural speech interaction acceptance protocol

The selected XIAO Sense firmware uses the Xiaozhi realtime audio protocol,
real PDM microphone samples, the hardware I2S speaker reference and Espressif
ESP-SR AEC. The Mac's pinned Xiaozhi server now requests an urgent
decoder and I2S flush after two consecutive VAD-positive human frames within
300ms during **ordinary** assistant speech or coordinated fleet speech.

The live acoustic evidence needs the physical XIAO Sense, selected MAX98357A
amplifier and actual 8 ohm speaker/enclosure. The active Sense pin contract
(`code/firmware/head/sense/config.h`) uses 16 kHz PDM input on GPIO42/41
and 32 kHz I2S output on GPIO4/7/8. The 16 kHz digital AEC reference is
derived from accepted speaker PCM; it is not proof of audible playback.
There is no MCU-controlled amplifier shutdown pin in this profile.

Use the current [mandatory audio trial record contract](../guides/audio-barge-in.md)
rather than the original twenty-trial proposal. The local private JSONL
input to `code/scripts/check_barge_in_trials.py` needs 42 records for full
coverage: 20 human interruptions at 50 cm (45–55 cm), 20 at 100 cm
(95–105 cm), one robot-only control and one quiet-mode control. A single
complete distance population is diagnostic only and cannot pass the
overall proposed gate.

Each distance population must cover all three intended volumes, early
and late interruption, voice-only, camera/WiFi and motor/servo stand
loads, at least two human speakers and adjacent conversation turns.
Every human record must include the guide's conditions, measured room
noise, unique trial ID and same-assembly provenance, and must confirm
audible robot speech at onset. Record six ordered timestamps on one
rebased monotonic clock: `human_onset_ms`, `vad_arrival_ms`,
`abort_dispatch_ms`, `head_queue_clear_ms`, `i2s_stop_ms` and
`audible_stop_ms`. Trials must not overlap. Record actual retained
utterance, intelligible beginning, correct intent and absence of
obsolete audio replay as specified in the guide.

The separate robot-only control needs at least 600 seconds, actual
audible speech at all three intended volumes, at least 120 cumulative
seconds of speech in the first ten minutes, at least five seconds in
each minute, matching measured minute exposures and zero self
interruptions. The quiet-mode control needs at least 600 seconds with
quiet enabled and zero unsolicited speech or motion. Both controls
must use the same robot, firmware, audio configuration and mic/speaker
placement as the human trials.

At each distance, the proposed gate requires at least 19 of 20 audible
stops within 500 ms and 18 of 20 correctly retained and understood
intents, with no obsolete audio replay and both controls passing.
The checker also reports `meets_120ms_i2s_cutoff` separately: all 20
trials at each distance must have positive onset-to-I2S-stop latency
within 120 ms for that metric. It is not folded into
`meets_proposed_gate`, and I2S stop alone does not prove audible silence.

Run `python code/scripts/check_barge_in_trials.py /private/trials.jsonl`
from the repository root with actual measured observations. Inspect
`meets_proposed_gate` and the separate I2S metric; exit status zero
alone is not a pass. The checker validates operator-supplied records,
not their physical authenticity. Keep synchronized acoustic recordings
and device logs private; never commit raw voices. Physical A2 remains
unqualified until actual bench evidence is reviewed.

The historical 90 ms AEC reference offset was a provisional software
baseline, **not** a verified measurement. The selected Sense private bench
image now must report `CONFIG_DESK_ROBOT_AEC_DELAY_MS=0` to avoid
subtracting an unknown offset before measuring actual acoustic lag.
Use the consent gated, authenticated `code/scripts/capture_sense_aec.py`
to record 4 seconds of real 16 kHz microphone and digital speaker
reference samples from the existing Sense codec, following
`docs/guides/sense-aec-port.md`. Then run
`code/scripts/estimate_aec_delay.py` on the locally protected WAVs.
No script, digital reference counter, synthetic test, or HTTP WAV transfer
establishes human double talk, analog audible playback position, or A2
physical acceptance. Reflash the normal image with PCM capture disabled
after the trials.

Moshi MLX from https://github.com/kyutai-labs/moshi is a genuine Mac
full-duplex speech-to-speech model option, but it is NOT a compatible
drop-in for Xiaozhi Opus, tools and security. The current task retains
Xiaozhi until its acoustic path has been physically qualified.
