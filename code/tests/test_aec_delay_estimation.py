"""Simulated audio tests do not establish physical echo cancellation."""
import runpy
from pathlib import Path

import numpy as np
import pytest

source = runpy.run_path(str(
    Path(__file__).resolve().parents[1] / "scripts/estimate_aec_delay.py"
))
estimate_delay = source["estimate_delay"]
resample_reference = source["resample_reference"]


def test_estimates_positive_lag_from_correlated_playback():
    rng = np.random.default_rng(21)
    speaker = rng.normal(0, 0.2, 8000)
    lag = 1120
    mic = np.concatenate([np.zeros(lag), speaker])[:8000]
    report = estimate_delay(speaker, mic)
    assert report["sample_lag"] == 1120
    assert report["reference_delay_ms"] == 70.0
    assert report["normalized_correlation"] > 0.8
    assert not report["aec_physically_verified"]
    assert not report["natural_barge_in_verified"]


def test_silence_uncorrelated_or_nonfinite_cannot_fake_calibration():
    with pytest.raises(ValueError):
        estimate_delay(np.zeros(1000), np.ones(1000))
    rng = np.random.default_rng(29)
    with pytest.raises(ValueError):
        estimate_delay(rng.normal(size=10000), rng.normal(size=10000))
    for value in (float("nan"), float("inf")):
        signal = np.ones(1000)
        signal[0] = value
        with pytest.raises(ValueError):
            estimate_delay(signal, np.ones(1000))


def test_sample_rate_and_window_are_strict():
    signal = np.ones(1000)
    with pytest.raises(ValueError):
        estimate_delay(signal, signal, sample_rate=24000)
    with pytest.raises(ValueError):
        estimate_delay(signal, signal, max_delay_ms=2)
    with pytest.raises(ValueError):
        resample_reference(signal, 48000)
    assert len(resample_reference(np.zeros(24000), 24000)) == 16000
