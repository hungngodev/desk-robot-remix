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

The separate code/scripts/estimate_aec_delay.py estimates lag from
synchronized actual playback and microphone PCM WAV files and helps tune
CONFIG_DESK_ROBOT_AEC_DELAY_MS from its provisional 90ms. A synthetic
test passing is not human double-talk qualification.

Moshi MLX from https://github.com/kyutai-labs/moshi is a genuine Mac
full-duplex speech-to-speech model option, but it is NOT a compatible
drop-in for Xiaozhi Opus, tools and security. The current task retains
Xiaozhi until its acoustic path has been physically qualified.
