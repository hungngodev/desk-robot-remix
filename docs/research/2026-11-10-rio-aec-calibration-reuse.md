# RIO audio reference timing reuse for actual acoustic calibration

The selected SenseReferenceCodec adapts the MIT licensed RIO playback reference idea. The existing Xiaozhi/Espressif AFE owns cancellation and voice detection. The fixed 90 ms build default is not physically calibrated. Do not install a second AEC or RIO's separate residual gate.

## Implemented calibration path

The selected speaker output is 32 kHz; the codec converts accepted post-volume playback PCM to 16 kHz and interleaves it with actual 16 kHz PDM microphone PCM **before** AFE processing. I2S acceptance does not establish audible sound or acoustic cancellation.

Use the existing authenticated, consented four-second `code/scripts/capture_sense_aec.py` procedure in [Sense AEC port](../guides/sense-aec-port.md). The temporary bench build requires `CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED=y` and `CONFIG_DESK_ROBOT_AEC_DELAY_MS=0`. Start broadband playback before capture and keep it active. Playback/reference reset or privacy revocation may invalidate the recording; an aborted recording is not convergence or barge-in evidence.

After capture writes both private 16 kHz WAV files:

```sh
cd code
uv run --no-sync python scripts/estimate_aec_delay.py \
  --speaker data/private/aec_lab_trial/speaker_reference.wav \
  --microphone data/private/aec_lab_trial/microphone.wav
```

The estimator accepts mono PCM16 speaker reference at 16, 24 or 32 kHz and mic at 16 kHz. The 24 kHz option is historical, not the current amplifier clock. It rejects ambiguous correlation peaks, invalid lengths and insufficient signal; aligned 4–10 second recordings support four-window clock drift diagnostics. Its integer `esp_idf_delay_setting_ms` is only a candidate when applicable (0–250 ms), not a hardware qualification. Repeat captures and review reference integrity and drift before changing the private per-unit setting.

## EXP-062 physical evidence boundary

The pinned Xiaozhi AFE initializes FD low-cost cancellation, very aggressive nonlinear suppression and VAD mode 0. These are configuration choices, not measured sensitivity or convergence. The current capture contains pre-AFE signals only.

| Property | Evidence still required |
| --- | --- |
| Convergence/reacquisition | Synchronized actual pre-AFE microphone, reference and post-AFE PCM during far-end-only broadband playback from cold start and after echo-path change; record windowed echo suppression and time to a declared stable target. Raw correlation is not ERLE. |
| Double talk | Separate labeled near-end-only, far-end-only and simultaneous speech trials; measure misses, false triggers, retained first words and audible STOP. Follow [the physical barge-in gate](../guides/audio-barge-in.md): 19/20 audible stops within 500 ms and 18/20 correct retained intents at each of 50 and 100 cm, with robot-only and quiet controls. |
| Speaker distortion | Measure actual acoustic output with an independent calibrated microphone at low/middle/high intended playback volume and fixed geometry; inspect clipping and harmonic/intermodulation products, separating speaker/amplifier distortion from microphone overload and room noise. Digital gain is not a measured nonlinear speaker model. |

Additional post-AFE or independent acoustic measurements must retain explicit consent, bounded private capture, generation/privacy revocation and secure deletion. No second live audio owner. Do not commit raw audio. Record board, firmware, configuration, geometry, levels, trial coverage, target and actual measurement receipts. All three acoustic questions remain OPEN; do not tune filter length, suppression or VAD thresholds from synthetic tests or correlation alone.

Sources: [pinned RIO aec.cpp](https://github.com/mk14ray/RIO-XIAO-ESP32-S3-Gemini-Live-Voice-Assistant/blob/b911305e48ce6a1b75fe6c07fc02f86ad7bfeb0a/aec.cpp), [pinned Xiaozhi AFE](https://github.com/78/xiaozhi-esp32/blob/c435f99a88066029ec2dbd2d758c8cc9d051565b/main/audio/engines/afe_audio_engine.cc), [Espressif AEC](https://docs.espressif.com/projects/esp-sr/en/latest/esp32s3/acoustic_echo_cancellation/README.html) (latest reference, not proof of pinned build performance), [Microsoft AEC Challenge](https://github.com/microsoft/AEC-Challenge) (evaluation reference only).
