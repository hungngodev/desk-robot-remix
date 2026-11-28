"""A stable but excessive clock slip must not advertise a fixed AEC setting."""
import json
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
import pytest


@pytest.mark.parametrize("ppm", [0, 50, 200, -200])
def test_cli_with_clock_slip(tmp_path, ppm):
    rng = np.random.default_rng(281)
    # Slightly band-limit the broadband stimulus so global correlation still
    # finds a peak even when the delay drifts over the ten-second recording.
    ref = np.convolve(rng.normal(0, 0.15, 160000), np.ones(8) / 8, mode="same")
    pos = np.arange(len(ref))
    mic = np.interp(pos - 1120 - pos * ppm / 1_000_000, pos, ref, left=0, right=0)
    for name, samples in (("speaker.wav", ref), ("mic.wav", mic)):
        with wave.open(str(tmp_path / name), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(np.rint(samples * 32768).astype("<i2").tobytes())
    script = Path(__file__).resolve().parents[1] / "scripts/estimate_aec_delay.py"
    result = subprocess.run(
        [sys.executable, str(script), "--speaker", str(tmp_path / "speaker.wav"),
         "--microphone", str(tmp_path / "mic.wav")],
        capture_output=True, text=True, check=True, timeout=30,
    )
    report = json.loads(result.stdout)
    needs_review = abs(ppm) > 100
    assert report["clock_drift_ppm_estimate"] == pytest.approx(ppm, abs=25)
    assert report["clock_drift_needs_hardware_review"] is needs_review
    assert report["esp_idf_delay_setting_applicable"] is not needs_review
    assert report["esp_idf_delay_setting_ms"] == (None if needs_review else 70)
    assert report["aec_physically_verified"] is False
    assert report["natural_barge_in_verified"] is False
