# RIO audio reference timing reuse for actual acoustic calibration

This repository already uses the MIT licensed RIO playback reference idea inside SenseReferenceCodec, with Xiaozhi/Espressif AFE processing actual MIC and playback reference samples. A random fixed 90ms delay cannot be treated as physically calibrated.

New script: code/scripts/estimate_aec_delay.py. It estimates the lag via established NumPy FFT cross-correlation using synchronized mono 16-bit WAV recordings, speaker at 16 or 24 kHz and microphone at 16 kHz. It rejects silent, uncorrelated, badly formatted or oversized files and emits no assertion of acoustic or barge-in qualification.

Example after capturing real synchronized PCM from the XIAO Sense audio tasks:

    cd code
    uv run python scripts/estimate_aec_delay.py --speaker /private/speaker.wav --microphone /private/mic.wav

The script does not record audio or alter firmware. Do not commit recordings. The device AFE must then be tuned and actually tested for the 19/20 natural interruption acceptance objective with real microphone and speaker. A result from synthesized WAVs is only a unit test.

Sources: https://github.com/mk14ray/RIO-XIAO-ESP32-S3-Gemini-Live-Voice-Assistant/blob/b911305e48ce6a1b75fe6c07fc02f86ad7bfeb0a/aec.cpp and https://docs.espressif.com/projects/esp-sr/en/latest/esp32s3/acoustic_echo_cancellation/README.html .
