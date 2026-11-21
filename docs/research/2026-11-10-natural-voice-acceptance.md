# Natural speech interaction acceptance protocol

The selected XIAO Sense firmware uses the Xiaozhi realtime audio protocol,
real PDM microphone samples, the hardware I2S speaker reference and Espressif
ESP-SR AEC. The Mac's pinned Xiaozhi server now requests an urgent
decoder and I2S flush after two consecutive VAD-positive human frames within
300ms during **ordinary** assistant speech or coordinated fleet speech.

The live acoustic evidence needs a physical XIAO device, actual 8 ohm speaker,
real microphone and one quiet room test. The new tool accepts a local private
JSONL file with exactly 20 human interruption records across low, medium and
high speaker volumes, plus one 600 second robot-only speech control record.

Human records need kind=human, unique id, volume, human_onset_ms,
audible_stop_ms, new_utterance_captured and new_intent_correct fields.
Robot-only record needs kind=robot_only, duration_seconds>=600 and
self_interruptions. The success gate is at least 19 of 20 audible speaker
stops within 500ms, 18 of 20 new intents understood, and zero robot-only
false interruptions.

Run python code/scripts/check_barge_in_trials.py /private/trials.jsonl
using actual manually measured observations. Never commit the raw voices.
The code cannot establish that supplied records really came from a robot.

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
